"""Data migration helper from legacy SQLite database to the unified platform database."""
from __future__ import annotations

import argparse
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, Optional

import pathlib
import sys

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import text

from platform_app import create_app
from extensions import db
from modules.propostas.models import (
    Equipment,
    ParamCategory,
    ParamOption,
    Proposal,
    SystemOptionOverride,
    User,
    ServicoType,
    ModalidadeType,
)

ROLE_MAP = {
    "admin": "admin",
    "gestor": "gestor",
    "usuario": "user",
}

def _to_bool(value: object) -> bool:
    if value in (None, "", "0"):
        return False
    return bool(value)


def _parse_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None

def _row_value(row: sqlite3.Row, key: str):
    try:
        return row[key]
    except KeyError:
        return None


@dataclass
class MigrationStats:
    inserted: Dict[str, int]
    updated: Dict[str, int]
    skipped: Dict[str, int]

    def __init__(self) -> None:
        self.inserted = defaultdict(int)
        self.updated = defaultdict(int)
        self.skipped = defaultdict(int)

    def report(self) -> str:
        sections = []
        for label, bucket in (("inserted", self.inserted), ("updated", self.updated), ("skipped", self.skipped)):
            if not bucket:
                continue
            entries = ", ".join(f"{key}: {value}" for key, value in sorted(bucket.items()))
            sections.append(f"{label}: {entries}")
        return " | ".join(sections)


def _open_sqlite(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite source not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _target_session():
    session = db.session
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


def _map_role(tipo: Optional[str]) -> str:
    return ROLE_MAP.get((tipo or "").lower(), "user")


def migrate_users(rows: Iterable[sqlite3.Row], stats: MigrationStats) -> Dict[int, int]:
    user_id_map: Dict[int, int] = {}
    for row in rows:
        legacy_id = row["id"]
        usuario = (row["usuario"] or "").strip() or None
        email = (row["email"] or "").strip()
        if not email:
            stats.skipped["users"] += 1
            continue

        existing = (
            User.query.filter((User.email == email) | (User.usuario == usuario))
            .order_by(User.id)
            .first()
        )
        senha_hash = _row_value(row, "senha_hash") or _row_value(row, "password_hash")
        role = _map_role(row["tipo"])

        if existing:
            changed = False
            if not senha_hash:
                senha_hash = existing.password_hash
            if not existing.usuario and usuario:
                existing.usuario = usuario
                changed = True
            if not existing.nome_completo and row["nome_completo"]:
                existing.nome_completo = row["nome_completo"]
                changed = True
            if senha_hash and existing.password_hash != senha_hash:
                existing.password_hash = senha_hash
                changed = True
            if existing.role != role:
                existing.role = role
                changed = True
            if existing.tipo != row["tipo"]:
                existing.tipo = row["tipo"]
                changed = True
            if row["signature_path"] and existing.signature_path != row["signature_path"]:
                existing.signature_path = row["signature_path"]
                changed = True
            if row["prox_num"] and existing.prox_num != row["prox_num"]:
                existing.prox_num = row["prox_num"]
                changed = True

            if changed:
                stats.updated["users"] += 1
            else:
                stats.skipped["users"] += 1
            user_id_map[legacy_id] = existing.id
            continue

        if not senha_hash:
            stats.skipped["users"] += 1
            continue

        new_user = User(
            id=legacy_id,
            usuario=usuario,
            nome_completo=row["nome_completo"],
            email=email,
            password_hash=senha_hash,
            tipo=row["tipo"],
            role=role,
            is_active=True,
            signature_path=row["signature_path"],
            prox_num=row["prox_num"] or 1,
        )
        db.session.add(new_user)
        stats.inserted["users"] += 1
        user_id_map[legacy_id] = legacy_id

    db.session.flush()
    return user_id_map


def migrate_param_options(rows: Iterable[sqlite3.Row], stats: MigrationStats, user_id_map: Dict[int, int]) -> None:
    for row in rows:
        category = row["category"]
        label = row["label"]
        existing = ParamOption.query.filter_by(category=ParamCategory(category), label=label).first()
        created_by_id = user_id_map.get(row["created_by_id"]) if row["created_by_id"] else None
        if existing:
            if created_by_id and existing.created_by_id != created_by_id:
                existing.created_by_id = created_by_id
                stats.updated["param_options"] += 1
            else:
                stats.skipped["param_options"] += 1
            continue
        opt = ParamOption(
            id=row["id"],
            category=ParamCategory(category),
            label=label,
            created_by_id=created_by_id,
        )
        db.session.add(opt)
        stats.inserted["param_options"] += 1
    db.session.flush()


def migrate_equipments(rows: Iterable[sqlite3.Row], stats: MigrationStats) -> Dict[int, int]:
    equipment_id_map: Dict[int, int] = {}
    for row in rows:
        name = (row["name"] or "").strip()
        existing = Equipment.query.filter_by(name=name).first() if name else None
        if existing:
            stats.skipped["equipments"] += 1
            equipment_id_map[row["id"]] = existing.id
            continue
        equipment = Equipment(
            id=row["id"],
            name=name,
            description=row["description"],
            unit_price=row["unit_price"],
            quantity=row["quantity"],
        )
        equipment._illustration_path = _row_value(row, "illustration_path")
        db.session.add(equipment)
        stats.inserted["equipments"] += 1
        equipment_id_map[row["id"]] = row["id"]
    db.session.flush()
    return equipment_id_map


def migrate_proposals(
    rows: Iterable[sqlite3.Row],
    stats: MigrationStats,
    user_id_map: Dict[int, int],
) -> Dict[int, int]:
    proposal_id_map: Dict[int, int] = {}
    for row in rows:
        legacy_id = row["id"]
        if Proposal.query.get(legacy_id):
            stats.skipped["proposals"] += 1
            proposal_id_map[legacy_id] = legacy_id
            continue

        usuario_id = user_id_map.get(row["usuario_id"])
        if not usuario_id:
            stats.skipped["proposals"] += 1
            continue

        try:
            servico_type = ServicoType(row["servico_type"]) if row["servico_type"] else ServicoType.PONTO
        except Exception:
            servico_type = ServicoType.PONTO

        try:
            modalidade_type = (
                ModalidadeType(row["modalidade_type"]) if row["modalidade_type"] else ModalidadeType.AQUISICAO
            )
        except Exception:
            modalidade_type = ModalidadeType.AQUISICAO

        proposal = Proposal(
            id=legacy_id,
            company=row["company"],
            cnpj=row["cnpj"],
            client_name=row["client_name"],
            email=row["email"],
            telefone=row["telefone"],
            pagamento=row["pagamento"],
            prazo_entrega=row["prazo_entrega"],
            frete=row["frete"],
            validade=row["validade"],
            garantia=row["garantia"],
            garantia_sistema=row["garantia_sistema"],
            servico_type=servico_type,
            modalidade_type=modalidade_type,
            enviar_email=_to_bool(row["enviar_email"]),
            email_corpo=row["email_corpo"],
            email_cc=row["email_cc"],
            data_criacao=_parse_datetime(row["data_criacao"]) or datetime.utcnow(),
            usuario_id=usuario_id,
            filename=row["filename"],
            sistema_ativo=_to_bool(row["sistema_ativo"]),
            sistema_nome=row["sistema_nome"],
            sistema_descricao=row["sistema_descricao"],
            sistema_imagem=row["sistema_imagem"],
            sistema_quantidade=row["sistema_quantidade"],
            sistema_preco_unitario=row["sistema_preco_unitario"],
            sistema_preco_total=row["sistema_preco_total"],
        )
        db.session.add(proposal)
        stats.inserted["proposals"] += 1
        proposal_id_map[legacy_id] = legacy_id
    db.session.flush()
    return proposal_id_map


def migrate_proposal_equipments(rows: Iterable[sqlite3.Row], proposal_map: Dict[int, int], equipment_map: Dict[int, int], stats: MigrationStats) -> None:
    link_table = db.metadata.tables["proposal_equipments"]
    insert_rows = []
    for row in rows:
        p_id = proposal_map.get(row["proposal_id"])
        e_id = equipment_map.get(row["equipment_id"])
        if not p_id or not e_id:
            stats.skipped["proposal_equipments"] += 1
            continue
        exists = db.session.execute(
            link_table.select()
            .where(link_table.c.proposal_id == p_id)
            .where(link_table.c.equipment_id == e_id)
        ).first()
        if exists:
            stats.skipped["proposal_equipments"] += 1
            continue
        insert_rows.append({"proposal_id": p_id, "equipment_id": e_id})

    if insert_rows:
        db.session.execute(link_table.insert(), insert_rows)
        stats.inserted["proposal_equipments"] += len(insert_rows)


def migrate_system_overrides(rows: Iterable[sqlite3.Row], stats: MigrationStats) -> None:
    for row in rows:
        key = row["key"]
        existing = SystemOptionOverride.query.filter_by(key=key).first()
        if existing:
            stats.skipped["system_option_overrides"] += 1
            continue
        override = SystemOptionOverride(
            id=row["id"],
            key=key,
            description=row["description"],
            image_path=row["image_path"],
            updated_at=row["updated_at"],
        )
        db.session.add(override)
        stats.inserted["system_option_overrides"] += 1
    db.session.flush()


def migrate_sqlite(source_path: str, disable_fk: bool = True) -> MigrationStats:
    stats = MigrationStats()
    conn = _open_sqlite(source_path)
    try:
        with _target_session():
            if disable_fk and db.engine.dialect.name.startswith("mysql"):
                db.session.execute(text("SET FOREIGN_KEY_CHECKS=0"))

            user_rows = conn.execute("SELECT * FROM users").fetchall()
            user_id_map = migrate_users(user_rows, stats)

            param_rows = conn.execute("SELECT * FROM param_options").fetchall()
            migrate_param_options(param_rows, stats, user_id_map)

            equipment_rows = conn.execute("SELECT * FROM equipments").fetchall()
            equipment_map = migrate_equipments(equipment_rows, stats)

            proposal_rows = conn.execute("SELECT * FROM proposals").fetchall()
            proposal_map = migrate_proposals(proposal_rows, stats, user_id_map)

            proposal_eq_rows = conn.execute("SELECT * FROM proposal_equipments").fetchall()
            migrate_proposal_equipments(proposal_eq_rows, proposal_map, equipment_map, stats)

            overrides_rows = conn.execute("SELECT * FROM system_option_overrides").fetchall()
            migrate_system_overrides(overrides_rows, stats)

            if disable_fk and db.engine.dialect.name.startswith("mysql"):
                db.session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        conn.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data into the unified platform database.")
    parser.add_argument(
        "--source",
        default=os.path.join("instance", "equipments.db"),
        help="Path to the legacy SQLite database (default: instance/equipments.db)",
    )
    parser.add_argument(
        "--target",
        help="SQLAlchemy database URI for the destination. Overrides the configured SQLALCHEMY_DATABASE_URI.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and compare data without committing changes.",
    )
    args = parser.parse_args()

    if args.target:
        os.environ["SQLALCHEMY_DATABASE_URI"] = args.target

    app = create_app()

    with app.app_context():
        if args.dry_run:
            with db.session.begin_nested():
                stats = migrate_sqlite(args.source)
                db.session.rollback()
        else:
            stats = migrate_sqlite(args.source)

    print("Migration completed.")
    print(stats.report() or "No changes applied.")


if __name__ == "__main__":
    main()









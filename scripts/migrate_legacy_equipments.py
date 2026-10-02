"""CLI utility to import legacy equipment records from an SQLite dump."""
from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from platform_app import create_app  # type: ignore
from extensions import db  # type: ignore
from modules.propostas.models import Equipment  # type: ignore


@dataclass
class EquipmentStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    def as_line(self) -> str:
        parts: list[str] = []
        if self.inserted:
            parts.append(f"inserted={self.inserted}")
        if self.updated:
            parts.append(f"updated={self.updated}")
        if self.skipped:
            parts.append(f"skipped={self.skipped}")
        return ", ".join(parts) or "no changes"


def _prepare_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _coerce_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sync_single(row: sqlite3.Row, stats: EquipmentStats, *, match_by_name: bool) -> None:
    legacy_id = row["id"]
    name = (row["name"] or "").strip()
    if not name:
        stats.skipped += 1
        return

    existing = db.session.get(Equipment, legacy_id)
    if existing is None and match_by_name and name:
        existing = Equipment.query.filter_by(name=name).first()

    description = row["description"]
    illustration = row["illustration_path"]
    unit_price = _coerce_float(row["unit_price"])
    quantity = _coerce_int(row["quantity"])

    if existing:
        changed = False
        if existing.name != name:
            existing.name = name
            changed = True
        if existing.description != description:
            existing.description = description
            changed = True
        if existing.unit_price != unit_price:
            existing.unit_price = unit_price
            changed = True
        if existing.quantity != quantity:
            existing.quantity = quantity
            changed = True

        previous_path = existing.illustration_path
        existing.illustration_path = illustration
        if existing.illustration_path != previous_path:
            changed = True
        if changed:
            stats.updated += 1
        else:
            stats.skipped += 1
        return

    equipment = Equipment(
        id=legacy_id,
        name=name,
        description=description,
        unit_price=unit_price,
        quantity=quantity,
    )
    equipment.illustration_path = illustration
    db.session.add(equipment)
    stats.inserted += 1


def sync_equipments(conn: sqlite3.Connection, *, match_by_name: bool) -> EquipmentStats:
    stats = EquipmentStats()
    try:
        rows = conn.execute("SELECT * FROM equipments").fetchall()
    except sqlite3.OperationalError as exc:
        raise RuntimeError("Table 'equipments' not found in legacy database") from exc

    for row in rows:
        _sync_single(row, stats, match_by_name=match_by_name)

    return stats


def run_sync(sqlite_path: Path, dry_run: bool = False, *, match_by_name: bool = False) -> EquipmentStats:
    conn = _prepare_sqlite(sqlite_path)
    try:
        if dry_run:
            with db.session.begin_nested():
                stats = sync_equipments(conn, match_by_name=match_by_name)
                db.session.rollback()
                return stats
        stats = sync_equipments(conn, match_by_name=match_by_name)
        db.session.commit()
        return stats
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import equipment data from a legacy SQLite database into the configured SQLAlchemy database.",
    )
    parser.add_argument(
        "--sqlite",
        default=Path("migrations") / "equipments.db",
        type=Path,
        help="Path to the legacy SQLite database (default: migrations/equipments.db)",
    )
    parser.add_argument(
        "--target",
        help="Optional SQLAlchemy database URI for the destination override.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and compare records without committing changes.",
    )
    parser.add_argument(
        "--match-by-name",
        action="store_true",
        help="Fallback to matching by equipment name when an id is missing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.target:
        os.environ["SQLALCHEMY_DATABASE_URI"] = args.target

    app = create_app()

    with app.app_context():
        Equipment.__table__.create(bind=db.engine, checkfirst=True)
        stats = run_sync(args.sqlite, dry_run=args.dry_run, match_by_name=args.match_by_name)

    mode = "dry-run" if args.dry_run else "applied"
    print(f"Equipment sync {mode}: {stats.as_line()}")


if __name__ == "__main__":
    main()

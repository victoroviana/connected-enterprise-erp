"""Crachá: recibos do legado."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from utils.helpers import (
    wants_json as _wants_json,
    paginate as _paginate,
    format_date as _format_date,
)
import hashlib
import math
import os
import time
import re
import unicodedata
import uuid
import zipfile

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from extensions import db
from modules.propostas.blueprints.auth import login_required
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions


cracha_bp = Blueprint("cracha_bp", __name__, url_prefix="/cracha")

ALLOWED_DEPTS = {"CRACHA"}
ALLOWED_UNITS = [
    "Sollus Tecnologia",
    "Sollus Campos",
    "Sollus Espirito Santo",
    "Sollus Curitiba",
]
ALLOWED_EXTENSIONS = {".pdf"}
CRACHA_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CRACHA_UPLOAD_DIRNAME = "uploads/cracha"
CRACHA_CUTTER_DIRNAME = "uploads/cracha_cortes"
RECIBO_SIGNED_DIRNAME = "uploads/recibos_assinados"
CRACHA_PLACEHOLDER_FRONT = "images/cracha_frente.jpg"
CRACHA_PLACEHOLDER_VERSO = "images/cracha_verso.jpg"
RESULTS_PER_PAGE = 10
PHOTO_CUTTER_SIZE = (300, 400)
PHOTO_CUTTER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
STATUS_TABS = (
    {"label": "Todos", "value": ""},
    {"label": "Pendentes", "value": "nao_assinado"},
    {"label": "Assinados", "value": "assinado"},
)


def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            cleaned = (name or "").strip()
            if cleaned:
                normalized = unicodedata.normalize("NFKD", cleaned)
                normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                names.add(normalized.upper())
    except Exception:
        return set()
    return names


def _legacy_cracha_table_statements() -> list[tuple[str, str]]:
    return [
        (
            "ja_emp_empresas",
            "CREATE TABLE IF NOT EXISTS ja_emp_empresas ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome varchar(255) NOT NULL,"
            "ativo tinyint(1) DEFAULT 1"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_emp_empresas_usuarios",
            "CREATE TABLE IF NOT EXISTS ja_emp_empresas_usuarios ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idempresas_fk int NOT NULL,"
            "idusuarios_fk int NOT NULL,"
            "KEY idx_empresas_usuarios_empresa (idempresas_fk),"
            "KEY idx_empresas_usuarios_usuario (idusuarios_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cli_clientes",
            "CREATE TABLE IF NOT EXISTS ja_cli_clientes ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome_fantasia varchar(255),"
            "razao_social varchar(255),"
            "cnpj varchar(50),"
            "cpf varchar(50),"
            "inscricao_estadual varchar(50),"
            "rg varchar(50),"
            "telefone1 varchar(50),"
            "telefone2 varchar(50),"
            "telefone3 varchar(50),"
            "telefone4 varchar(50),"
            "email varchar(255),"
            "website varchar(255),"
            "endereco varchar(255),"
            "endereco_numero varchar(50),"
            "endereco_complemento varchar(255),"
            "endereco_bairro varchar(255),"
            "endereco_municipio varchar(255),"
            "endereco_uf varchar(10),"
            "endereco_cep varchar(20),"
            "fax varchar(50),"
            "tipo varchar(20),"
            "ativo tinyint(1) DEFAULT 1,"
            "idlocalidades_fk int,"
            "contato varchar(255),"
            "contato_setor varchar(255),"
            "idempresas_fk int,"
            "KEY idx_cli_clientes_empresa (idempresas_fk),"
            "KEY idx_cli_clientes_nome (nome_fantasia)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_usr_usuarios",
            "CREATE TABLE IF NOT EXISTS ja_usr_usuarios ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome varchar(255),"
            "login varchar(255),"
            "senha varchar(255),"
            "email varchar(255),"
            "idclientes_fk int,"
            "ativo tinyint(1) DEFAULT 1,"
            "senha2 varchar(255),"
            "KEY idx_usr_usuarios_cliente (idclientes_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_sys_ufs",
            "CREATE TABLE IF NOT EXISTS ja_sys_ufs ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "sigla varchar(5) NOT NULL,"
            "estado varchar(255) NOT NULL"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_prm_localidades",
            "CREATE TABLE IF NOT EXISTS ja_prm_localidades ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "localidade varchar(255) NOT NULL"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_produtos_grupo",
            "CREATE TABLE IF NOT EXISTS ja_pro_produtos_grupo ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome varchar(255) NOT NULL,"
            "ativo tinyint(1) DEFAULT 1"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_produtos_marca",
            "CREATE TABLE IF NOT EXISTS ja_pro_produtos_marca ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome varchar(255) NOT NULL,"
            "ativo tinyint(1) DEFAULT 1"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_fornecedor",
            "CREATE TABLE IF NOT EXISTS ja_pro_fornecedor ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "nome varchar(255) NOT NULL,"
            "ativo tinyint(1) DEFAULT 1"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_produtos",
            "CREATE TABLE IF NOT EXISTS ja_pro_produtos ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "produto varchar(255),"
            "codigo varchar(50),"
            "controlado_numero_serie tinyint(1) DEFAULT 0,"
            "observacoes text,"
            "idprodutos_grupo_fk int,"
            "idprodutos_marca_fk int,"
            "codigo_marca varchar(50)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_produtos_detalhe",
            "CREATE TABLE IF NOT EXISTS ja_pro_produtos_detalhe ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idprodutos_fk int,"
            "quantidade_minima int,"
            "quantidade_maxima int,"
            "ativo tinyint(1) DEFAULT 1,"
            "idempresas_fk int,"
            "corredor varchar(50),"
            "prateleira varchar(50),"
            "gaveta varchar(50),"
            "quantidade_atual int,"
            "armario varchar(50),"
            "palete varchar(50),"
            "KEY idx_produtos_detalhe_produto (idprodutos_fk),"
            "KEY idx_produtos_detalhe_empresa (idempresas_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_pro_produtos_numeros_series",
            "CREATE TABLE IF NOT EXISTS ja_pro_produtos_numeros_series ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idprodutos_fk int,"
            "numero_serie varchar(255),"
            "KEY idx_produtos_series_produto (idprodutos_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cra_crachas_modelos",
            "CREATE TABLE IF NOT EXISTS ja_cra_crachas_modelos ("
            "id_pk int NOT NULL AUTO_INCREMENT PRIMARY KEY,"
            "idclientes_fk int NOT NULL,"
            "frente varchar(255),"
            "verso varchar(255),"
            "situacao tinyint(1) DEFAULT 0,"
            "obs_frente text,"
            "obs_verso text,"
            "KEY idx_crachas_modelos_cliente (idclientes_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cra_crachas_extratos",
            "CREATE TABLE IF NOT EXISTS ja_cra_crachas_extratos ("
            "id_pk int NOT NULL AUTO_INCREMENT PRIMARY KEY,"
            "idclientes_fk int NOT NULL,"
            "quantidade int NOT NULL,"
            "entrada_saida int NOT NULL,"
            "idprodutos_fk int NOT NULL,"
            "descricao varchar(255),"
            "data date NOT NULL,"
            "KEY idx_crachas_extratos_cliente (idclientes_fk),"
            "KEY idx_crachas_extratos_produto (idprodutos_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cli_contrato_locacao_manutencao",
            "CREATE TABLE IF NOT EXISTS ja_cli_contrato_locacao_manutencao ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idclientes_fk int NOT NULL,"
            "manutencao_hardeware tinyint(1),"
            "manutencao_software tinyint(1),"
            "locacao tinyint(1),"
            "contrato_numero varchar(50),"
            "tipo_atendimento int,"
            "valor decimal(12,2),"
            "reposicao_de_peca tinyint(1),"
            "ficha_manutencao tinyint(1),"
            "nota_fiscal tinyint(1),"
            "emissao_boleto tinyint(1),"
            "data_assinatura date,"
            "vigencia int,"
            "idcontrato_locacao_manutencao_fk int,"
            "tipo_pagamento int,"
            "KEY idx_contratos_cliente (idclientes_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cli_contrato_localidade_equipamento",
            "CREATE TABLE IF NOT EXISTS ja_cli_contrato_localidade_equipamento ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idcontrato_locacao_manutencao_fk int NOT NULL,"
            "endereco_cliente tinyint(1),"
            "descricao varchar(255),"
            "endereco varchar(255),"
            "endereco_numero varchar(50),"
            "endereco_complemento varchar(255),"
            "endereco_bairro varchar(255),"
            "endereco_municipio varchar(255),"
            "endereco_uf varchar(10),"
            "endereco_cep varchar(20),"
            "idlocalidades_fk int,"
            "contato varchar(255),"
            "contato_setor varchar(255),"
            "telefone1 varchar(50),"
            "telefone2 varchar(50),"
            "telefone3 varchar(50),"
            "telefone4 varchar(50),"
            "email varchar(255),"
            "KEY idx_contrato_localidade_contrato (idcontrato_locacao_manutencao_fk),"
            "KEY idx_contrato_localidade_localidade (idlocalidades_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cli_contrato_equipamentos",
            "CREATE TABLE IF NOT EXISTS ja_cli_contrato_equipamentos ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "marca varchar(255),"
            "modelo varchar(255),"
            "numero_serie varchar(255),"
            "modelo_software varchar(255),"
            "capacidade varchar(255),"
            "idcontrato_localidade_equipamento_fk int NOT NULL,"
            "KEY idx_contrato_equip_localidade (idcontrato_localidade_equipamento_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_fin_contas_a_receber_contratos",
            "CREATE TABLE IF NOT EXISTS ja_fin_contas_a_receber_contratos ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "data_vencimento date,"
            "data_pagamento date,"
            "valor_cobrado decimal(12,2),"
            "valor_pago decimal(12,2),"
            "idcontrato_locacao_manutencao_fk int NOT NULL,"
            "KEY idx_contas_receber_contrato (idcontrato_locacao_manutencao_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "ja_cli_manutencao_agendamentos",
            "CREATE TABLE IF NOT EXISTS ja_cli_manutencao_agendamentos ("
            "id_pk int NOT NULL PRIMARY KEY,"
            "idusuarios_fk int,"
            "data date,"
            "hora_entrada time,"
            "hora_saida time,"
            "data_inicio_para_atendimento date,"
            "idcontrato_localidade_equipamento_fk int NOT NULL,"
            "KEY idx_manutencao_localidade (idcontrato_localidade_equipamento_fk)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "controle_de_crachas",
            "CREATE TABLE IF NOT EXISTS controle_de_crachas ("
            "id int NOT NULL PRIMARY KEY,"
            "cliente varchar(255),"
            "cnpj varchar(20),"
            "quantidade_em_estoque int,"
            "ultima_modificacao datetime,"
            "criado_por varchar(255),"
            "unidade enum('Sollus Tecnologia','Sollus Campos','Sollus Espirito Santo','Sollus Curitiba') NOT NULL"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "recibos",
            "CREATE TABLE IF NOT EXISTS recibos ("
            "id int NOT NULL PRIMARY KEY,"
            "numero_recibo varchar(20),"
            "cliente varchar(100),"
            "endereco varchar(200),"
            "cnpj varchar(20),"
            "quantidade_entregue int,"
            "descricao varchar(200),"
            "quantidade_anterior int,"
            "quantidade_restante int,"
            "pedido varchar(50),"
            "data_pedido date,"
            "unidade enum('Sollus Tecnologia','Sollus Campos','Sollus Espirito Santo','Sollus Curitiba') NOT NULL,"
            "url_recibo varchar(255),"
            "data_criacao datetime,"
            "tipo_cracha varchar(255)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
        (
            "pedidos_cracha",
            "CREATE TABLE IF NOT EXISTS pedidos_cracha ("
            "id int NOT NULL AUTO_INCREMENT PRIMARY KEY,"
            "empresa varchar(255) NOT NULL,"
            "data_solicitacao date NOT NULL,"
            "etapa varchar(50) NOT NULL,"
            "observacoes text,"
            "data_criacao datetime DEFAULT CURRENT_TIMESTAMP,"
            "criado_por varchar(255),"
            "quantidade int DEFAULT 1,"
            "tipo varchar(50) DEFAULT 'cracha'"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        ),
    ]


def ensure_cracha_legacy_tables() -> None:
    if db.engine.dialect.name == "sqlite":
        return
    statements = _legacy_cracha_table_statements()

    for name, stmt in statements:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao garantir tabela %s", name)

    # Dynamic migrations for quantity and type columns in pedidos_cracha
    try:
        db.session.execute(text("SELECT quantidade FROM pedidos_cracha LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(text("ALTER TABLE pedidos_cracha ADD COLUMN quantidade int DEFAULT 1"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    try:
        db.session.execute(text("SELECT tipo FROM pedidos_cracha LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(text("ALTER TABLE pedidos_cracha ADD COLUMN tipo varchar(50) DEFAULT 'cracha'"))
            db.session.commit()
        except Exception:
            db.session.rollback()


def _project_root() -> Path:
    return Path(current_app.root_path).parent


def _cracha_upload_dir() -> Path:
    return _project_root() / CRACHA_UPLOAD_DIRNAME


def _cracha_cutter_dir() -> Path:
    return _project_root() / CRACHA_CUTTER_DIRNAME


def _cracha_cutter_batch_dir(batch_id: str) -> Path:
    safe_batch = secure_filename(batch_id or "")
    return _cracha_cutter_dir() / safe_batch


def _cleanup_old_cracha_cuts(max_age_seconds: int = 3600) -> None:
    base = _cracha_cutter_dir()
    if not base.exists():
        return
    now = time.time()
    for path in base.iterdir():
        try:
            age = now - path.stat().st_mtime
            if age < max_age_seconds:
                continue
            if path.is_dir():
                for child in path.iterdir():
                    if child.is_file():
                        child.unlink(missing_ok=True)
                path.rmdir()
            elif path.is_file():
                path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning("Nao foi possivel limpar corte antigo: %s", path)


def _process_cracha_photo(input_path: Path, output_path: Path) -> bool:
    try:
        import cv2
        import face_recognition
    except ImportError as exc:
        raise RuntimeError(
            "Dependencias do cortador de fotos ausentes. Instale face_recognition, opencv-python e numpy."
        ) from exc

    img_original = cv2.imread(str(input_path))
    if img_original is None:
        raise ValueError("Imagem invalida ou nao pode ser lida.")

    orig_height, orig_width = img_original.shape[:2]
    scale = 1.0
    hd_width, hd_height = 1280, 720
    if orig_width > hd_width or orig_height > hd_height:
        scale = min(hd_width / orig_width, hd_height / orig_height)
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)
        img_detection = cv2.resize(
            img_original,
            (new_width, new_height),
            interpolation=cv2.INTER_LANCZOS4,
        )
    else:
        img_detection = img_original.copy()

    img_detection_rgb = cv2.cvtColor(img_detection, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(img_detection_rgb, model="hog")
    detected_face = bool(face_locations)

    if detected_face:
        top, right, bottom, left = face_locations[0]
        top_orig = int(top / scale)
        right_orig = int(right / scale)
        bottom_orig = int(bottom / scale)
        left_orig = int(left / scale)

        vertical_margin = int((bottom_orig - top_orig) * 0.7)
        top_adj = max(top_orig - vertical_margin, 0)
        bottom_adj = min(bottom_orig + vertical_margin, orig_height)

        face_height = bottom_adj - top_adj
        required_width = int(face_height * 3 / 4)
        center_x = (left_orig + right_orig) // 2
        left_adj = max(center_x - required_width // 2, 0)
        right_adj = min(left_adj + required_width, orig_width)

        if right_adj - left_adj < required_width:
            left_adj = max(right_adj - required_width, 0)

        cropped = img_original[top_adj:bottom_adj, left_adj:right_adj]
    else:
        cropped = img_original

    final = cv2.resize(cropped, PHOTO_CUTTER_SIZE, interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(output_path), final, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return detected_face


def _is_admin_user() -> bool:
    role = normalize_role_key(getattr(current_user, "tipo", None) or "")
    return role == "admin"




def _deny_access():
    if _wants_json():
        return jsonify({"ok": False, "message": "Sem permiss\u00e3o para crach\u00e1."}), 403
    flash("Voc\u00ea n\u00e3o tem permiss\u00e3o para acessar crach\u00e1. Procure seu superior.", "warning")
    return redirect(url_for("cracha_bp.sem_permissao"))


@cracha_bp.before_request
def _check_cracha_permissions():
    from flask import request
    if "/api/" in getattr(request, "path", ""):
        return
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("cracha_bp."):
        return
    if endpoint == "cracha_bp.sem_permissao":
        return
    if endpoint in {"cracha_bp.recibo_arquivo", "cracha_bp.cracha_arquivo"}:
        return
    if endpoint in {"cracha_bp.pedidos", "cracha_bp.pedidos_historico"}:
        return

    if not current_user.is_authenticated:
        return

    if _is_admin_user() or (_dept_names() & ALLOWED_DEPTS):
        return

    # Restrict modifications (creating, editing, stage updates, deleting) to admin or CRACHA department only
    if endpoint in {
        "cracha_bp.pedidos_criar",
        "cracha_bp.pedidos_editar",
        "cracha_bp.pedidos_atualizar_etapa",
        "cracha_bp.pedidos_excluir"
    }:
        return _deny_access()

    perms = current_permissions()

    if perms.get("cracha"):
        return

    # Cortador de Fotos
    if endpoint.startswith("cracha_bp.cortador_fotos"):
        if perms.get("cracha_cortador"):
            return
        return _deny_access()

    # Clientes
    if endpoint.startswith("cracha_bp.clientes"):
        if perms.get("cracha_clientes"):
            return
        return _deny_access()

    # Modelos / Crachás
    if endpoint.startswith("cracha_bp.modelos"):
        if perms.get("cracha_modelos"):
            return
        return _deny_access()

    # Extratos
    if endpoint.startswith("cracha_bp.extratos"):
        if perms.get("cracha_extratos"):
            return
        return _deny_access()

    # Recibos / Consultar Estoque / Imprimir Recibo
    if (endpoint.startswith("cracha_bp.recibo") or
        endpoint in {
            "cracha_bp.criar_recibo",
            "cracha_bp.editar_recibo",
            "cracha_bp.assinar_recibo",
            "cracha_bp.excluir_recibo",
            "cracha_bp.consultar_estoque",
            "cracha_bp.imprimir_recibo"
        }):
        if perms.get("cracha_recibos"):
            return
        return _deny_access()

    # Produtos
    if endpoint.startswith("cracha_bp.produtos"):
        if perms.get("cracha_produtos"):
            return
        return _deny_access()

    # Fornecedores
    if endpoint.startswith("cracha_bp.fornecedor"):
        if perms.get("cracha_fornecedores"):
            return
        return _deny_access()

    # Empresas
    if endpoint.startswith("cracha_bp.empresas"):
        if perms.get("cracha_empresas"):
            return
        return _deny_access()

    if any(perms.get(k) for k in [
        "cracha_clientes", "cracha_modelos", "cracha_extratos", "cracha_recibos",
        "cracha_cortador", "cracha_produtos", "cracha_fornecedores", "cracha_empresas"
    ]):
        return

    return _deny_access()


@cracha_bp.route("/sem-permissao")
@login_required
def sem_permissao():
    return render_template("errors/403.html", area_label="Crachá")


def _sanitize_photo_filename(filename: str) -> str:
    if not filename:
        return ""
    # Normaliza separadores e obtém apenas o nome do arquivo
    name = os.path.basename(filename.replace("\\", "/")).strip()
    # Remove caracteres inválidos para sistemas de arquivos (Windows, Linux, macOS)
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    # Remove caracteres de controle ASCII
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    # Remove pontos e espaços iniciais/finais redundantes
    name = name.strip(". ")
    return name


@cracha_bp.route("/cortador-fotos")
@login_required
def cortador_fotos():
    return render_template("admin/cracha/cortador_fotos.html")


@cracha_bp.route("/cortador-fotos/processar", methods=["POST"])
@login_required
def cortador_fotos_processar():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "message": "Envie pelo menos uma imagem."}), 400

    _cleanup_old_cracha_cuts()
    batch_id = uuid.uuid4().hex
    batch_dir = _cracha_cutter_batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    results = []
    errors = []
    for file_storage in files:
        original_name = _sanitize_photo_filename(file_storage.filename or "")
        suffix = Path(original_name).suffix.lower()
        if not original_name or suffix not in PHOTO_CUTTER_EXTS:
            errors.append({"name": original_name or "arquivo", "error": "Formato nao suportado."})
            continue

        source_name = f"original_{uuid.uuid4().hex}{suffix}"
        source_path = batch_dir / source_name
        output_name = f"{Path(original_name).stem or 'foto'}.jpg"
        output_path = batch_dir / output_name
        counter = 2
        while output_path.exists():
            output_name = f"{Path(original_name).stem or 'foto'}_{counter}.jpg"
            output_path = batch_dir / output_name
            counter += 1

        try:
            file_storage.save(source_path)
            detected = _process_cracha_photo(source_path, output_path)
            source_path.unlink(missing_ok=True)
            results.append(
                {
                     "name": output_name,
                     "original_name": original_name,
                     "detected": detected,
                     "url": url_for(
                         "cracha_bp.cortador_fotos_arquivo",
                         batch_id=batch_id,
                         filename=output_name,
                     ),
                }
            )
        except Exception as exc:
            source_path.unlink(missing_ok=True)
            current_app.logger.exception("Falha ao cortar foto de cracha: %s", original_name)
            errors.append({"name": original_name, "error": str(exc)})

    if not results and errors:
        return jsonify({"ok": False, "message": errors[0]["error"], "errors": errors}), 500

    return jsonify({"ok": True, "batch_id": batch_id, "images": results, "errors": errors})


@cracha_bp.route("/cortador-fotos/arquivo/<batch_id>/<path:filename>")
@login_required
def cortador_fotos_arquivo(batch_id: str, filename: str):
    batch_dir = _cracha_cutter_batch_dir(batch_id)
    safe_name = _sanitize_photo_filename(filename)
    return send_from_directory(batch_dir, safe_name, as_attachment=safe_name.lower().endswith(".zip"))


@cracha_bp.route("/cortador-fotos/download", methods=["POST"])
@login_required
def cortador_fotos_download():
    data = request.get_json(silent=True) or {}
    batch_id = secure_filename(data.get("batch_id") or "")
    names = [_sanitize_photo_filename(str(name)) for name in data.get("names", []) if name]
    if not batch_id or not names:
        return jsonify({"ok": False, "message": "Selecione pelo menos uma foto para baixar."}), 400

    batch_dir = _cracha_cutter_batch_dir(batch_id)
    if not batch_dir.exists():
        return jsonify({"ok": False, "message": "Arquivos de corte nao encontrados."}), 404

    zip_name = f"fotos_crachas_{batch_id}.zip"
    zip_path = batch_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for name in names:
            file_path = batch_dir / name
            if file_path.is_file() and file_path.suffix.lower() == ".jpg":
                zip_file.write(file_path, arcname=name)

    return jsonify(
        {
            "ok": True,
            "download_url": url_for(
                "cracha_bp.cortador_fotos_arquivo",
                batch_id=batch_id,
                filename=zip_name,
            ),
        }
    )


def _signed_dir() -> Path:
    root = Path(current_app.root_path).parent
    return root / RECIBO_SIGNED_DIRNAME


def _resolve_recibo_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    filename = os.path.basename(raw)
    if not filename:
        return raw
    return url_for("cracha_bp.recibo_arquivo", filename=filename)




def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_allowed_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in CRACHA_IMAGE_EXTS


def _save_cracha_file(file_storage, *, prefix: str) -> str | None:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    filename = secure_filename(file_storage.filename)
    if not filename or not _is_allowed_image(filename):
        return None
    upload_dir = _cracha_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}-{int(time.time())}-{filename}"
    target = upload_dir / name
    file_storage.save(target)
    return name


def _delete_cracha_file(filename: str | None) -> None:
    if not filename:
        return
    try:
        target = _cracha_upload_dir() / Path(filename).name
        if target.exists():
            target.unlink()
    except Exception:
        pass


def _resolve_cracha_image_url(filename: str | None, fallback: str) -> str:
    if filename:
        safe_name = Path(str(filename)).name
        if safe_name:
            return url_for("cracha_bp.cracha_arquivo", filename=safe_name)
    return url_for("static", filename=fallback)




def _build_url(endpoint: str, **updates: Any) -> str:
    args = dict(request.args)
    for key, value in updates.items():
        if value in (None, ""):
            args.pop(key, None)
        else:
            args[key] = value
    return url_for(endpoint, **args)


def _fetch_clientes(only_active: bool = True) -> list[dict[str, Any]]:
    where = "WHERE ativo = 1" if only_active else ""
    rows = db.session.execute(
        text(f"SELECT id_pk, nome_fantasia FROM ja_cli_clientes {where} ORDER BY nome_fantasia")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_produtos() -> list[dict[str, Any]]:
    rows = db.session.execute(
        text("SELECT id_pk, produto FROM ja_pro_produtos ORDER BY produto")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_empresas(only_active: bool = False) -> list[dict[str, Any]]:
    where = "WHERE ativo = 1" if only_active else ""
    rows = db.session.execute(
        text(f"SELECT id_pk, nome, ativo FROM ja_emp_empresas {where} ORDER BY nome")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_ufs() -> list[dict[str, Any]]:
    rows = db.session.execute(
        text("SELECT id_pk, sigla, estado FROM ja_sys_ufs ORDER BY sigla")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_localidades() -> list[dict[str, Any]]:
    rows = db.session.execute(
        text("SELECT id_pk, localidade FROM ja_prm_localidades ORDER BY localidade")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_grupos() -> list[dict[str, Any]]:
    rows = db.session.execute(
        text("SELECT id_pk, nome, ativo FROM ja_pro_produtos_grupo ORDER BY nome")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _fetch_marcas() -> list[dict[str, Any]]:
    rows = db.session.execute(
        text("SELECT id_pk, nome, ativo FROM ja_pro_produtos_marca ORDER BY nome")
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _build_modelos_filters(search: str) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("(c.nome_fantasia LIKE :search OR c.razao_social LIKE :search)")
        params["search"] = f"%{search}%"
    return where, params


def _build_extratos_filters(search: str) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("(c.nome_fantasia LIKE :search OR c.razao_social LIKE :search OR c.cnpj LIKE :search)")
        params["search"] = f"%{search}%"
    return where, params


def _build_base_filters(
    *,
    pesquisa: str,
    data_inicio: str,
    data_fim: str,
) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}

    if pesquisa:
        where.append("(numero_recibo LIKE :pesquisa OR cliente LIKE :pesquisa OR cnpj LIKE :pesquisa)")
        params["pesquisa"] = f"%{pesquisa}%"

    if data_inicio and data_fim:
        where.append("data_criacao BETWEEN :inicio AND :fim")
        params["inicio"] = data_inicio
        params["fim"] = f"{data_fim} 23:59:59"

    return where, params


def _fetch_status_counts(
    *,
    pesquisa: str,
    data_inicio: str,
    data_fim: str,
) -> dict[str, int]:
    where, params = _build_base_filters(
        pesquisa=pesquisa,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    where_sql = " AND ".join(where) if where else "1 = 1"

    row = db.session.execute(
        text(
            "SELECT "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN url_recibo IS NULL OR url_recibo = '' THEN 1 ELSE 0 END) AS pendentes, "
            "SUM(CASE WHEN url_recibo IS NOT NULL AND url_recibo != '' THEN 1 ELSE 0 END) AS assinados "
            f"FROM recibos WHERE {where_sql}"
        ),
        params,
    ).fetchone()

    total = _safe_int(row[0]) if row else 0
    pendentes = _safe_int(row[1]) if row else 0
    assinados = _safe_int(row[2]) if row else 0

    return {
        "": total,
        "nao_assinado": pendentes,
        "assinado": assinados,
    }


def _next_recibo_id() -> int:
    row = db.session.execute(text("SELECT MAX(id) AS max_id FROM recibos")).fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    return int(max_id) + 1


def _numero_recibo(next_id: int) -> str:
    padded = str(next_id).rjust(4, "1")
    return f"{padded}/{datetime.now().year}"


def _next_cracha_cliente_id() -> int:
    row = db.session.execute(
        text("SELECT MAX(id) AS max_id FROM controle_de_crachas")
    ).fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    return int(max_id) + 1


def _next_id(table: str, column: str = "id_pk") -> int:
    row = db.session.execute(text(f"SELECT MAX({column}) AS max_id FROM {table}")).fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    return int(max_id) + 1


def _parse_date_br(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _bool_from_form(value: Any) -> int:
    if value in (None, "", False):
        return 0
    raw = str(value).strip().lower()
    return 1 if raw in {"1", "true", "t", "sim", "yes", "y", "on"} else 0


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _numero_por_extenso(numero: int) -> str:
    numeros = {
        1: "um",
        2: "dois",
        3: "tres",
        4: "quatro",
        5: "cinco",
        6: "seis",
        7: "sete",
        8: "oito",
        9: "nove",
        10: "dez",
        11: "onze",
        12: "doze",
        13: "treze",
        14: "quatorze",
        15: "quinze",
        16: "dezesseis",
        17: "dezessete",
        18: "dezoito",
        19: "dezenove",
        20: "vinte",
        30: "trinta",
        40: "quarenta",
        50: "cinquenta",
        60: "sessenta",
        70: "setenta",
        80: "oitenta",
        90: "noventa",
        100: "cem",
        200: "duzentos",
        300: "trezentos",
        400: "quatrocentos",
        500: "quinhentos",
        600: "seiscentos",
        700: "setecentos",
        800: "oitocentos",
        900: "novecentos",
        1000: "mil",
    }

    if numero <= 20 or numero in (100, 1000):
        return numeros.get(numero, str(numero))
    if numero < 100:
        dezena = (numero // 10) * 10
        unidade = numero % 10
        return numeros.get(dezena, str(dezena)) + (f" e {_numero_por_extenso(unidade)}" if unidade else "")
    centena = (numero // 100) * 100
    dezena = numero % 100
    if dezena == 0:
        return numeros.get(centena, str(centena))
    return numeros.get(centena, str(centena)) + f" e {_numero_por_extenso(dezena)}"


@cracha_bp.route("/recibos")
@login_required
def recibos():
    pesquisa = (request.args.get("pesquisa") or "").strip()
    data_inicio = (request.args.get("data_inicio") or "").strip()
    data_fim = (request.args.get("data_fim") or "").strip()
    filtro_status = (request.args.get("filtro_status") or "").strip()

    page = _safe_int(request.args.get("page"), 1)
    if page < 1:
        page = 1
    per_page = 10
    offset = (page - 1) * per_page

    where, params = _build_base_filters(
        pesquisa=pesquisa,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    if not where:
        where = ["1 = 1"]

    if filtro_status == "nao_assinado":
        where.append("(url_recibo IS NULL OR url_recibo = '')")
    elif filtro_status == "assinado":
        where.append("(url_recibo IS NOT NULL AND url_recibo != '')")

    where_sql = " AND ".join(where)
    if filtro_status == "assinado":
        order_sql = "ORDER BY data_pedido ASC"
    else:
        order_sql = (
            "ORDER BY CASE WHEN url_recibo IS NULL OR url_recibo = '' THEN 0 ELSE 1 END ASC, "
            "data_pedido ASC"
        )

    total = 0
    items: list[dict[str, Any]] = []
    try:
        total = db.session.execute(
            text(f"SELECT COUNT(*) AS total FROM recibos WHERE {where_sql}"),
            params,
        ).scalar() or 0
        rows = db.session.execute(
            text(
                "SELECT id, numero_recibo, cliente, cnpj, unidade, quantidade_entregue, "
                "quantidade_restante, data_criacao, data_pedido, tipo_cracha, url_recibo "
                f"FROM recibos WHERE {where_sql} {order_sql} LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": per_page, "offset": offset},
        ).fetchall()
        for row in rows:
            data = dict(row._mapping)
            data["data_criacao_br"] = _format_date(data.get("data_criacao"))
            data["data_pedido_br"] = _format_date(data.get("data_pedido"))
            data["download_url"] = _resolve_recibo_url(data.get("url_recibo"))
            data["is_signed"] = bool(data.get("url_recibo"))
            items.append(data)
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao carregar recibos")

    total_pages = max(1, math.ceil(total / per_page)) if total else 1

    status_counts = _fetch_status_counts(
        pesquisa=pesquisa,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    filtros = {
        "pesquisa": pesquisa,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "filtro_status": filtro_status,
    }
    next_id = None
    try:
        next_id = _next_recibo_id()
    except Exception:
        next_id = None

    return render_template(
        "admin/cracha/recibos.html",
        recibos=items,
        page=page,
        total_pages=total_pages,
        total_items=total,
        filtros=filtros,
        status_tabs=STATUS_TABS,
        status_counts=status_counts,
        status_value=filtro_status,
        next_recibo_numero=_numero_recibo(next_id) if next_id else "",
        allowed_units=ALLOWED_UNITS,
        build_url=_build_url,
    )


@cracha_bp.route("/controle")
@login_required
def controle_crachas():
    return redirect(url_for("cracha_bp.extratos"))
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("(cliente LIKE :search OR cnpj LIKE :search)")
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = 0
    total_estoque = 0
    clientes_rows: list[dict[str, Any]] = []
    try:
        total = db.session.execute(
            text(f"SELECT COUNT(*) AS total FROM controle_de_crachas WHERE {where_sql}"),
            params,
        ).scalar() or 0
        total_estoque = db.session.execute(
            text(f"SELECT SUM(quantidade_em_estoque) FROM controle_de_crachas WHERE {where_sql}"),
            params,
        ).scalar() or 0
        rows = db.session.execute(
            text(
                "SELECT id, cliente, cnpj, quantidade_em_estoque, ultima_modificacao, criado_por, unidade "
                f"FROM controle_de_crachas WHERE {where_sql} "
                "ORDER BY cliente ASC "
                "LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": per_page, "offset": offset},
        ).fetchall()
        for row in rows:
            data = dict(row._mapping)
            data["ultima_modificacao_br"] = _format_date(data.get("ultima_modificacao")) or "-"
            clientes_rows.append(data)
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao carregar clientes de cracha")

    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/cracha/controle.html",
        clientes=clientes_rows,
        total_items=total,
        total_estoque=total_estoque,
        search=search,
        pagination=pagination,
        allowed_units=ALLOWED_UNITS,
        build_url=_build_url,
    )


@cracha_bp.route("/controle/criar", methods=["POST"])
@login_required
def criar_cliente_cracha():
    cnpj = (request.form.get("cnpj") or "").strip()
    cliente = (request.form.get("cliente") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    quantidade = _safe_int(request.form.get("quantidadeCrachas"))
    if not cnpj or not cliente or not unidade:
        flash("Preencha CNPJ, cliente e unidade.", "warning")
        return redirect(url_for("cracha_bp.controle_crachas"))
    if unidade not in ALLOWED_UNITS:
        flash("Unidade inv\u00e1lida.", "warning")
        return redirect(url_for("cracha_bp.controle_crachas"))

    criado_por = (
        (getattr(current_user, "name", None) or "").strip()
        or (getattr(current_user, "nome", None) or "").strip()
        or (getattr(current_user, "username", None) or "").strip()
        or "Sistema"
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        next_id = _next_cracha_cliente_id()
        db.session.execute(
            text(
                "INSERT INTO controle_de_crachas (id, cliente, cnpj, quantidade_em_estoque, "
                "ultima_modificacao, criado_por, unidade) "
                "VALUES (:id, :cliente, :cnpj, :quantidade, :ultima_modificacao, :criado_por, :unidade)"
            ),
            {
                "id": next_id,
                "cliente": cliente,
                "cnpj": cnpj,
                "quantidade": quantidade,
                "ultima_modificacao": now,
                "criado_por": criado_por,
                "unidade": unidade,
            },
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao criar cliente de cracha")
        flash("Erro ao adicionar cliente.", "danger")
        return redirect(url_for("cracha_bp.controle_crachas"))

    flash("Cliente adicionado com sucesso.", "success")
    return redirect(url_for("cracha_bp.controle_crachas"))


@cracha_bp.route("/controle/editar", methods=["POST"])
@login_required
def editar_cliente_cracha():
    cliente_id = _safe_int(request.form.get("id"))
    cliente = (request.form.get("cliente") or "").strip()
    cnpj = (request.form.get("cnpj") or "").strip()
    quantidade = _safe_int(request.form.get("quantidadeCrachas"))
    if not cliente_id:
        flash("Cliente inv\u00e1lido.", "warning")
        return redirect(url_for("cracha_bp.controle_crachas"))
    if not cliente or not cnpj:
        flash("Preencha cliente e CNPJ.", "warning")
        return redirect(url_for("cracha_bp.controle_crachas"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.session.execute(
            text(
                "UPDATE controle_de_crachas "
                "SET cliente = :cliente, cnpj = :cnpj, quantidade_em_estoque = :quantidade, "
                "ultima_modificacao = :ultima_modificacao "
                "WHERE id = :id"
            ),
            {
                "cliente": cliente,
                "cnpj": cnpj,
                "quantidade": quantidade,
                "ultima_modificacao": now,
                "id": cliente_id,
            },
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao editar cliente de cracha")
        flash("Erro ao atualizar cliente.", "danger")
        return redirect(url_for("cracha_bp.controle_crachas"))

    flash("Cliente atualizado.", "success")
    return redirect(url_for("cracha_bp.controle_crachas"))


@cracha_bp.route("/verifica-empresa")
@login_required
def cracha_verifica_empresa():
    cnpj = (request.args.get("cnpj") or "").strip()
    if not cnpj:
        return ""
    cnpj = re.sub(r"\D+", "", cnpj)

    row = db.session.execute(
        text("SELECT cliente FROM empresa WHERE cnpj = :cnpj"),
        {"cnpj": cnpj},
    ).fetchone()
    if row and row[0]:
        return str(row[0])

    try:
        import requests

        resp = requests.get(f"https://www.receitaws.com.br/v1/cnpj/{cnpj}", timeout=12)
        if resp.ok:
            data = resp.json()
            if data.get("nome"):
                return str(data.get("nome"))
    except Exception:
        current_app.logger.warning("Falha ao consultar receitaws para CNPJ %s", cnpj)

    return "CNPJ n\u00e3o encontrado."


@cracha_bp.route("/recibos/consultar-estoque")
@login_required
def consultar_estoque():
    cnpj = (request.args.get("cnpj") or "").strip()
    if not cnpj:
        return jsonify({"success": False, "message": "Informe o CNPJ."}), 400
    
    # Padronizar CNPJ: remover toda pontuação e manter apenas dígitos
    cnpj_clean = re.sub(r"\D+", "", cnpj)
    
    try:
        row = db.session.execute(
            text(
                "SELECT cliente, unidade, quantidade_em_estoque "
                "FROM controle_de_crachas WHERE cnpj = :cnpj"
            ),
            {"cnpj": cnpj_clean},
        ).fetchone()
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao consultar controle_de_crachas")
        return jsonify({"success": False, "message": "Erro ao consultar estoque."}), 500
    
    if not row:
        # Fallback: se não estiver no controle de crachás, buscar nas tabelas de clientes gerais
        try:
            row_cli = db.session.execute(
                text(
                    "SELECT id_pk, nome_fantasia, razao_social "
                    "FROM ja_cli_clientes WHERE cnpj = :cnpj LIMIT 1"
                ),
                {"cnpj": cnpj_clean},
            ).fetchone()
            if row_cli:
                nome_fantasia = row_cli.nome_fantasia
                razao_social = row_cli.razao_social
                nome_final = razao_social or nome_fantasia

                # Consultar saldo real no extrato mesmo sem registro em controle_de_crachas
                saldo_fallback = 0
                try:
                    cnpj_pattern = (cnpj_clean[:8] + "%") if len(cnpj_clean) >= 8 else (cnpj_clean + "%")
                    ext_row = db.session.execute(
                        text(
                            "SELECT SUM(e.quantidade * e.entrada_saida) AS saldo "
                            "FROM ja_cra_crachas_extratos e "
                            "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
                            "WHERE REPLACE(REPLACE(REPLACE(c.cnpj, '.', ''), '/', ''), '-', '') LIKE :cnpj_pattern"
                        ),
                        {"cnpj_pattern": cnpj_pattern},
                    ).fetchone()
                    if ext_row and ext_row[0] is not None:
                        saldo_fallback = int(ext_row[0])
                except SQLAlchemyError:
                    current_app.logger.warning(
                        "Falha ao calcular saldo do extrato no fallback para CNPJ %s", cnpj_clean
                    )

                return jsonify(
                    {
                        "success": True,
                        "nome_empresa": nome_final,
                        "unidade": "Sollus Tecnologia",
                        "total_estoque": saldo_fallback,
                    }
                )
        except SQLAlchemyError:
            current_app.logger.exception("Falha ao consultar ja_cli_clientes como fallback")
            
        return jsonify({"success": False, "message": "CNPJ não encontrado."}), 404
        
    data = dict(row._mapping)

    # Tentar calcular o saldo real a partir dos lançamentos do extrato.
    # O campo controle_de_crachas.quantidade_em_estoque é um cache que pode
    # ficar dessincronizado; ja_cra_crachas_extratos é a fonte canônica.
    saldo_real = None
    try:
        cnpj_pattern = (cnpj_clean[:8] + "%") if len(cnpj_clean) >= 8 else (cnpj_clean + "%")
        extrato_row = db.session.execute(
            text(
                "SELECT SUM(e.quantidade * e.entrada_saida) AS saldo "
                "FROM ja_cra_crachas_extratos e "
                "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
                "WHERE REPLACE(REPLACE(REPLACE(c.cnpj, '.', ''), '/', ''), '-', '') LIKE :cnpj_pattern"
            ),
            {"cnpj_pattern": cnpj_pattern},
        ).fetchone()
        if extrato_row and extrato_row[0] is not None:
            saldo_real = int(extrato_row[0])
            # Sincronizar o cache se houver discrepância
            if saldo_real != _safe_int(data.get("quantidade_em_estoque")):
                try:
                    db.session.execute(
                        text(
                            "UPDATE controle_de_crachas "
                            "SET quantidade_em_estoque = :saldo WHERE cnpj = :cnpj"
                        ),
                        {"saldo": saldo_real, "cnpj": cnpj_clean},
                    )
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    current_app.logger.warning(
                        "Não foi possível sincronizar estoque para CNPJ %s", cnpj_clean
                    )
    except SQLAlchemyError:
        current_app.logger.warning(
            "Falha ao calcular saldo do extrato para CNPJ %s", cnpj_clean
        )

    total_estoque = saldo_real if saldo_real is not None else _safe_int(data.get("quantidade_em_estoque"))
    return jsonify(
        {
            "success": True,
            "nome_empresa": data.get("cliente"),
            "unidade": data.get("unidade"),
            "total_estoque": total_estoque,
        }
    )


@cracha_bp.route("/recibos/criar", methods=["POST"])
@login_required
def criar_recibo():
    try:
        next_id = _next_recibo_id()
    except Exception:
        flash("N\u00e3o foi poss\u00edvel gerar o n\u00famero do recibo.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    numero_recibo = _numero_recibo(next_id)
    cliente = (request.form.get("cliente") or "").strip()
    endereco = (request.form.get("endereco") or "").strip()
    cnpj = re.sub(r"\D+", "", (request.form.get("cnpj") or "").strip())
    data_pedido = (request.form.get("dataPedido") or "").strip()
    pedido = (request.form.get("pedido") or "").strip()
    quantidade_entregue = _safe_int(request.form.get("quantidadeEntregue"))
    descricao = (request.form.get("descricao") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    tipo_cracha = (request.form.get("tipo_cracha") or "").strip()

    try:
        row = db.session.execute(
            text("SELECT quantidade_em_estoque FROM controle_de_crachas WHERE cnpj = :cnpj"),
            {"cnpj": cnpj},
        ).fetchone()
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao buscar estoque de crachas")
        flash("Erro ao consultar estoque de crachás.", "danger")
        return redirect(url_for("cracha_bp.recibos"))
        
    if not row:
        # Fallback para a tabela geral de clientes (ja_cli_clientes)
        try:
            row_cli = db.session.execute(
                text("SELECT nome_fantasia, razao_social FROM ja_cli_clientes WHERE cnpj = :cnpj LIMIT 1"),
                {"cnpj": cnpj},
            ).fetchone()
            if not row_cli:
                flash("CNPJ não cadastrado no sistema (não encontrado em controle de estoque nem na base de clientes).", "warning")
                return redirect(url_for("cracha_bp.recibos"))
            
            # Inicializa automaticamente no controle de crachás com estoque 0
            cli_name = row_cli.razao_social or row_cli.nome_fantasia or cliente
            db.session.execute(
                text(
                    "INSERT INTO controle_de_crachas (cliente, cnpj, quantidade_em_estoque, unidade) "
                    "VALUES (:cliente, :cnpj, 0, :unidade)"
                ),
                {
                    "cliente": cli_name,
                    "cnpj": cnpj,
                    "unidade": unidade or "Sollus Tecnologia"
                }
            )
            db.session.commit()
            estoque_cache = 0
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Falha ao criar registro controle_de_crachas automatico")
            flash("Erro ao inicializar controle de estoque para o CNPJ.", "danger")
            return redirect(url_for("cracha_bp.recibos"))
    else:
        estoque_cache = _safe_int(row[0])

    # Verificar saldo real calculado a partir do extrato (fonte canônica).
    # O campo quantidade_em_estoque em controle_de_crachas é um cache que pode
    # ficar dessincronizado com os lançamentos do extrato.
    estoque_atual = estoque_cache
    try:
        cnpj_limpo = re.sub(r"\D+", "", cnpj)
        cnpj_pattern = (cnpj_limpo[:8] + "%") if len(cnpj_limpo) >= 8 else (cnpj_limpo + "%")
        extrato_row = db.session.execute(
            text(
                "SELECT SUM(e.quantidade * e.entrada_saida) AS saldo "
                "FROM ja_cra_crachas_extratos e "
                "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
                "WHERE REPLACE(REPLACE(REPLACE(c.cnpj, '.', ''), '/', ''), '-', '') LIKE :cnpj_pattern"
            ),
            {"cnpj_pattern": cnpj_pattern},
        ).fetchone()
        if extrato_row and extrato_row[0] is not None:
            estoque_atual = int(extrato_row[0])
    except SQLAlchemyError:
        current_app.logger.warning(
            "Falha ao calcular saldo do extrato para CNPJ %s ao criar recibo; usando cache.", cnpj
        )

    quantidade_restante = estoque_atual - quantidade_entregue

    try:
        db.session.execute(
            text(
                "INSERT INTO recibos (id, numero_recibo, cliente, endereco, cnpj, data_pedido, "
                "pedido, quantidade_entregue, descricao, quantidade_anterior, quantidade_restante, "
                "unidade, tipo_cracha, data_criacao) "
                "VALUES (:id, :numero, :cliente, :endereco, :cnpj, :data_pedido, :pedido, "
                ":quantidade_entregue, :descricao, :quantidade_anterior, :quantidade_restante, "
                ":unidade, :tipo_cracha, :data_criacao)"
            ),
            {
                "id": next_id,
                "numero": numero_recibo,
                "cliente": cliente,
                "endereco": endereco,
                "cnpj": cnpj,
                "data_pedido": data_pedido or None,
                "pedido": pedido or None,
                "quantidade_entregue": quantidade_entregue,
                "descricao": descricao,
                "quantidade_anterior": estoque_atual,
                "quantidade_restante": quantidade_restante,
                "unidade": unidade,
                "tipo_cracha": tipo_cracha,
                "data_criacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        db.session.execute(
            text(
                "UPDATE controle_de_crachas SET quantidade_em_estoque = :restante "
                "WHERE cnpj = :cnpj"
            ),
            {"restante": quantidade_restante, "cnpj": cnpj},
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao criar recibo")
        flash("Erro ao criar recibo.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    flash("Recibo criado com sucesso.", "success")
    return redirect(url_for("cracha_bp.recibos"))


@cracha_bp.route("/recibos/<int:recibo_id>/json")
@login_required
def recibo_json(recibo_id: int):
    row = db.session.execute(
        text("SELECT * FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Recibo n\u00e3o encontrado."}), 404
    data = dict(row._mapping)
    if isinstance(data.get("data_pedido"), (datetime, date)):
        data["data_pedido"] = data["data_pedido"].strftime("%Y-%m-%d")
    data["is_signed"] = bool(data.get("url_recibo"))
    return jsonify({"success": True, "data": data})


@cracha_bp.route("/recibos/<int:recibo_id>/print-data")
@login_required
def recibo_print_data(recibo_id: int):
    row = db.session.execute(
        text("SELECT * FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Recibo n\u00e3o encontrado."}), 404
    data = dict(row._mapping)
    qtd_entregue = _safe_int(data.get("quantidade_entregue"))
    qtd_restante = _safe_int(data.get("quantidade_restante"))
    data["quantidade_entregue"] = qtd_entregue
    data["quantidade_restante"] = qtd_restante
    data["quantidade_entregue_extenso"] = _numero_por_extenso(qtd_entregue)
    data["quantidade_restante_extenso"] = _numero_por_extenso(qtd_restante)
    data["data_pedido_br"] = _format_date(data.get("data_pedido"))
    data["data_criacao_br"] = _format_date(data.get("data_criacao"))
    return jsonify({"success": True, "data": data})


@cracha_bp.route("/recibos/editar", methods=["POST"])
@login_required
def editar_recibo():
    recibo_id = _safe_int(request.form.get("id"))
    if not recibo_id:
        flash("Recibo inv\u00e1lido.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    row = db.session.execute(
        text("SELECT url_recibo FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        flash("Recibo n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    admin_password = (request.form.get("admin_password") or "").strip()
    if row[0] and admin_password != current_app.config.get("CRACHA_ADMIN_PASSWORD", "Sollus2025"):
        flash("Senha incorreta para editar recibo assinado.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    numero_recibo = (request.form.get("numeroRecibo") or "").strip()
    cnpj = re.sub(r"\D+", "", (request.form.get("cnpj") or "").strip())
    cliente = (request.form.get("cliente") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    endereco = (request.form.get("endereco") or "").strip()
    quantidade_anterior = _safe_int(request.form.get("totalEmEstoque"))
    quantidade_entregue = _safe_int(request.form.get("quantidadeEntregue"))
    tipo_cracha = (request.form.get("tipo_cracha") or "").strip()
    pedido = (request.form.get("pedido") or "").strip()
    data_pedido = (request.form.get("dataPedido") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()

    if unidade and unidade not in ALLOWED_UNITS:
        flash("Unidade inv\u00e1lida.", "warning")
        return redirect(url_for("cracha_bp.recibos"))
    if data_pedido and not re.match(r"^\d{4}-\d{2}-\d{2}$", data_pedido):
        flash("Data do pedido inv\u00e1lida.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    quantidade_restante = quantidade_anterior - quantidade_entregue

    try:
        db.session.execute(
            text(
                "UPDATE recibos SET numero_recibo = :numero, cliente = :cliente, cnpj = :cnpj, "
                "endereco = :endereco, unidade = :unidade, quantidade_entregue = :entregue, "
                "pedido = :pedido, data_pedido = :data_pedido, tipo_cracha = :tipo_cracha, "
                "descricao = :descricao, quantidade_anterior = :anterior, quantidade_restante = :restante "
                "WHERE id = :id"
            ),
            {
                "numero": numero_recibo,
                "cliente": cliente,
                "cnpj": cnpj,
                "endereco": endereco,
                "unidade": unidade,
                "entregue": quantidade_entregue,
                "pedido": pedido,
                "data_pedido": data_pedido or None,
                "tipo_cracha": tipo_cracha,
                "descricao": descricao,
                "anterior": quantidade_anterior,
                "restante": quantidade_restante,
                "id": recibo_id,
            },
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao editar recibo")
        flash("Erro ao atualizar recibo.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    flash("Recibo atualizado.", "success")
    return redirect(url_for("cracha_bp.recibos"))


@cracha_bp.route("/recibos/excluir", methods=["POST"])
@login_required
def excluir_recibo():
    if not _is_admin_user():
        return jsonify({"success": False, "message": "Sem permiss\u00e3o para excluir."}), 403
    recibo_id = _safe_int(request.form.get("id"))
    if not recibo_id:
        return jsonify({"success": False, "message": "ID inv\u00e1lido."}), 400

    row = db.session.execute(
        text("SELECT url_recibo FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Recibo n\u00e3o encontrado."}), 404
    if row[0]:
        return jsonify({"success": False, "message": "N\u00e3o \u00e9 poss\u00edvel excluir: recibo assinado."}), 400

    try:
        result = db.session.execute(
            text(
                "DELETE FROM recibos WHERE id = :id AND (url_recibo IS NULL OR url_recibo = '') LIMIT 1"
            ),
            {"id": recibo_id},
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"success": False, "message": "Falha ao excluir."}), 500

    if result.rowcount == 1:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Falha ao excluir."}), 500


@cracha_bp.route("/recibos/assinar", methods=["POST"])
@login_required
def assinar_recibo():
    recibo_id = _safe_int(request.form.get("id"))
    if not recibo_id:
        flash("Recibo inv\u00e1lido.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    file = request.files.get("recibo")
    if not file or file.filename == "":
        flash("Nenhum arquivo enviado.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    row = db.session.execute(
        text("SELECT url_recibo FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        flash("Recibo n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    already_signed = bool(row[0])
    admin_password = (request.form.get("admin_password") or "").strip()
    if already_signed and admin_password != current_app.config.get("CRACHA_ADMIN_PASSWORD", "Sollus2025"):
        flash("Senha incorreta para trocar o recibo assinado.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    filename = secure_filename(file.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash("Arquivo inv\u00e1lido. Envie um PDF.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    signed_dir = _signed_dir()
    signed_dir.mkdir(parents=True, exist_ok=True)

    if already_signed:
        try:
            old_filename = os.path.basename(str(row[0]))
            old_path = signed_dir / old_filename
            if old_filename and old_path.exists():
                old_path.unlink(missing_ok=True)
        except Exception:
            pass

    new_filename = f"{recibo_id}-{int(time.time())}{ext}"
    target_path = signed_dir / new_filename
    file.save(target_path)

    url_recibo = f"{RECIBO_SIGNED_DIRNAME}/{new_filename}"
    try:
        db.session.execute(
            text("UPDATE recibos SET url_recibo = :url WHERE id = :id"),
            {"url": url_recibo, "id": recibo_id},
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao salvar recibo assinado")
        flash("Erro ao salvar recibo assinado.", "danger")
        return redirect(url_for("cracha_bp.recibos"))

    flash("Recibo atualizado com sucesso.", "success")
    return redirect(url_for("cracha_bp.recibos"))


@cracha_bp.route("/recibos/arquivo/<path:filename>")
@login_required
def recibo_arquivo(filename: str):
    perms = current_permissions()
    has_perm = perms.get("cracha_recibos") or perms.get("cracha_extratos") or perms.get("cracha")
    if not (_is_admin_user() or (_dept_names() & ALLOWED_DEPTS) or has_perm):
        return _deny_access()
    safe_name = secure_filename(filename)
    if not safe_name:
        return _deny_access()
    return send_from_directory(_signed_dir(), safe_name, as_attachment=True)


@cracha_bp.route("/crachas/arquivo/<path:filename>")
@login_required
def cracha_arquivo(filename: str):
    perms = current_permissions()
    has_perm = perms.get("cracha") or any(perms.get(k) for k in [
        "cracha_clientes", "cracha_modelos", "cracha_extratos", "cracha_recibos",
        "cracha_cortador", "cracha_produtos", "cracha_fornecedores", "cracha_empresas"
    ])
    if not (_is_admin_user() or (_dept_names() & ALLOWED_DEPTS) or has_perm):
        return _deny_access()
    safe_name = Path(str(filename)).name
    if not safe_name or not _is_allowed_image(safe_name):
        return _deny_access()
    return send_from_directory(_cracha_upload_dir(), safe_name)


@cracha_bp.route("/recibos/imprimir/<int:recibo_id>")
@login_required
def imprimir_recibo(recibo_id: int):
    row = db.session.execute(
        text("SELECT * FROM recibos WHERE id = :id"),
        {"id": recibo_id},
    ).fetchone()
    if not row:
        flash("Recibo n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.recibos"))

    data = dict(row._mapping)
    qtd_entregue = _safe_int(data.get("quantidade_entregue"))
    qtd_restante = _safe_int(data.get("quantidade_restante"))
    data["quantidade_entregue_extenso"] = _numero_por_extenso(qtd_entregue)
    data["quantidade_restante_extenso"] = _numero_por_extenso(qtd_restante)
    data["data_pedido_br"] = _format_date(data.get("data_pedido"))
    data["data_criacao_br"] = _format_date(data.get("data_criacao"))

    return render_template("admin/cracha/imprimir_recibo.html", recibo=data)


@cracha_bp.route("/modelos")
@login_required
def modelos():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()

    where, params = _build_modelos_filters(search)
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(
            "SELECT COUNT(*) AS total "
            "FROM ja_cra_crachas_modelos m "
            "INNER JOIN ja_cli_clientes c ON (m.idclientes_fk = c.id_pk) "
            f"WHERE {where_sql}"
        ),
        params,
    ).scalar() or 0

    limit = RESULTS_PER_PAGE
    offset = (page - 1) * limit
    rows = db.session.execute(
        text(
            "SELECT m.id_pk, m.idclientes_fk, m.frente, m.verso, m.situacao, "
            "m.obs_frente, m.obs_verso, c.nome_fantasia, c.razao_social "
            "FROM ja_cra_crachas_modelos m "
            "INNER JOIN ja_cli_clientes c ON (m.idclientes_fk = c.id_pk) "
            f"WHERE {where_sql} "
            "ORDER BY c.nome_fantasia "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).fetchall()

    crachas: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        situacao_raw = str(data.get("situacao") or "").strip().lower()
        data["situacao_bool"] = situacao_raw in {"1", "true", "t", "sim"}
        data["frente_url"] = _resolve_cracha_image_url(
            data.get("frente"), CRACHA_PLACEHOLDER_FRONT
        )
        data["verso_url"] = _resolve_cracha_image_url(
            data.get("verso"), CRACHA_PLACEHOLDER_VERSO
        )
        crachas.append(data)

    pagination = _paginate(total, page, RESULTS_PER_PAGE)

    return render_template(
        "admin/cracha/modelos.html",
        crachas=crachas,
        pagination=pagination,
        search_value=search,
        build_url=lambda **kw: _build_url("cracha_bp.modelos", **kw),
    )


@cracha_bp.route("/modelos/novo", methods=["GET", "POST"])
@login_required
def modelos_novo():
    clientes = _fetch_clientes()
    cracha = {}

    if request.method == "POST":
        cliente_id = _safe_int(request.form.get("cliente_id"), 0)
        obs_frente = (request.form.get("obs_frente") or "").strip()
        obs_verso = (request.form.get("obs_verso") or "").strip()
        frente_file = request.files.get("frente")
        verso_file = request.files.get("verso")

        if not cliente_id:
            flash("Informe o cliente.", "warning")
        elif not frente_file or not frente_file.filename:
            flash("Envie a frente do crach\u00e1.", "warning")
        elif frente_file and not _is_allowed_image(frente_file.filename):
            flash("Arquivo de frente inv\u00e1lido. Use JPG ou PNG.", "warning")
        elif verso_file and verso_file.filename and not _is_allowed_image(verso_file.filename):
            flash("Arquivo de verso inv\u00e1lido. Use JPG ou PNG.", "warning")
        else:
            frente_name = _save_cracha_file(frente_file, prefix="frente") if frente_file else None
            verso_name = _save_cracha_file(verso_file, prefix="verso") if verso_file else None
            if not frente_name:
                flash("Erro ao salvar a imagem de frente.", "danger")
            else:
                db.session.execute(
                    text(
                        "INSERT INTO ja_cra_crachas_modelos "
                        "(idclientes_fk, frente, verso, situacao, obs_frente, obs_verso) "
                        "VALUES (:cliente, :frente, :verso, :situacao, :obs_frente, :obs_verso)"
                    ),
                    {
                        "cliente": cliente_id,
                        "frente": frente_name,
                        "verso": verso_name,
                        "situacao": 0,
                        "obs_frente": obs_frente or None,
                        "obs_verso": obs_verso or None,
                    },
                )
                db.session.commit()
                flash("Crach\u00e1 criado com sucesso.", "success")
                if request.form.get("save_more"):
                    return redirect(url_for("cracha_bp.modelos_novo"))
                return redirect(url_for("cracha_bp.modelos"))

        cracha = {
            "idclientes_fk": cliente_id,
            "obs_frente": obs_frente,
            "obs_verso": obs_verso,
        }

    return render_template(
        "admin/cracha/modelos_form.html",
        cracha=cracha,
        clientes=clientes,
        page_title="Novo crach\u00e1",
        action_url=url_for("cracha_bp.modelos_novo"),
        allow_save_more=True,
    )


@cracha_bp.route("/modelos/<int:cracha_id>/editar", methods=["GET", "POST"])
@login_required
def modelos_editar(cracha_id: int):
    row = db.session.execute(
        text("SELECT * FROM ja_cra_crachas_modelos WHERE id_pk = :id"),
        {"id": cracha_id},
    ).fetchone()
    if not row:
        flash("Crach\u00e1 n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.modelos"))

    cracha = dict(row._mapping)
    clientes = _fetch_clientes()

    if request.method == "POST":
        cliente_id = _safe_int(request.form.get("cliente_id"), 0)
        obs_frente = (request.form.get("obs_frente") or "").strip()
        obs_verso = (request.form.get("obs_verso") or "").strip()
        frente_file = request.files.get("frente")
        verso_file = request.files.get("verso")
        sem_verso = request.form.get("sem_verso") == "on"

        if not cliente_id:
            flash("Informe o cliente.", "warning")
        elif frente_file and frente_file.filename and not _is_allowed_image(frente_file.filename):
            flash("Arquivo de frente inv\u00e1lido. Use JPG ou PNG.", "warning")
        elif verso_file and verso_file.filename and not _is_allowed_image(verso_file.filename):
            flash("Arquivo de verso inv\u00e1lido. Use JPG ou PNG.", "warning")
        else:
            frente_name = cracha.get("frente")
            verso_name = cracha.get("verso")

            if frente_file and frente_file.filename:
                new_frente = _save_cracha_file(frente_file, prefix="frente")
                if new_frente:
                    _delete_cracha_file(frente_name)
                    frente_name = new_frente
            if verso_file and verso_file.filename:
                new_verso = _save_cracha_file(verso_file, prefix="verso")
                if new_verso:
                    _delete_cracha_file(verso_name)
                    verso_name = new_verso
            elif sem_verso:
                _delete_cracha_file(verso_name)
                verso_name = None

            db.session.execute(
                text(
                    "UPDATE ja_cra_crachas_modelos "
                    "SET idclientes_fk = :cliente, frente = :frente, verso = :verso, "
                    "obs_frente = :obs_frente, obs_verso = :obs_verso "
                    "WHERE id_pk = :id"
                ),
                {
                    "cliente": cliente_id,
                    "frente": frente_name,
                    "verso": verso_name,
                    "obs_frente": obs_frente or None,
                    "obs_verso": obs_verso or None,
                    "id": cracha_id,
                },
            )
            db.session.commit()
            flash("Crach\u00e1 atualizado.", "success")
            return redirect(url_for("cracha_bp.modelos"))

        cracha.update(
            {
                "idclientes_fk": cliente_id,
                "obs_frente": obs_frente,
                "obs_verso": obs_verso,
            }
        )

    cracha["frente_url"] = _resolve_cracha_image_url(
        cracha.get("frente"), CRACHA_PLACEHOLDER_FRONT
    )
    cracha["verso_url"] = _resolve_cracha_image_url(
        cracha.get("verso"), CRACHA_PLACEHOLDER_VERSO
    )

    return render_template(
        "admin/cracha/modelos_form.html",
        cracha=cracha,
        clientes=clientes,
        page_title="Editar crach\u00e1",
        action_url=url_for("cracha_bp.modelos_editar", cracha_id=cracha_id),
        allow_save_more=False,
    )


@cracha_bp.route("/modelos/<int:cracha_id>/excluir", methods=["POST"])
@login_required
def modelos_excluir(cracha_id: int):
    row = db.session.execute(
        text("SELECT frente, verso FROM ja_cra_crachas_modelos WHERE id_pk = :id"),
        {"id": cracha_id},
    ).fetchone()
    if not row:
        flash("Crach\u00e1 n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.modelos"))

    frente = row[0]
    verso = row[1]
    db.session.execute(
        text("DELETE FROM ja_cra_crachas_modelos WHERE id_pk = :id"),
        {"id": cracha_id},
    )
    db.session.commit()
    _delete_cracha_file(frente)
    _delete_cracha_file(verso)
    flash("Crach\u00e1 removido.", "success")
    return redirect(url_for("cracha_bp.modelos"))


@cracha_bp.route("/modelos/aprovacao-interna", methods=["POST"])
@login_required
def modelos_aprovacao_interna():
    cracha_id = _safe_int(request.form.get("id"))
    aprovar = (request.form.get("aprovar") or "").strip().lower() in {"1", "true", "t", "sim", "yes"}
    if not cracha_id:
        return jsonify({"ok": False, "message": "ID inv\u00e1lido."}), 400

    db.session.execute(
        text("UPDATE ja_cra_crachas_modelos SET situacao = :situacao WHERE id_pk = :id"),
        {"situacao": 1 if aprovar else 0, "id": cracha_id},
    )
    db.session.commit()
    return jsonify({"ok": True})


@cracha_bp.route("/extratos")
@login_required
def extratos():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()

    where, params = _build_extratos_filters(search)
    where_sql = " AND ".join(where) if where else "1 = 1"
    where_cc_sql = "(cc.cliente LIKE :search OR cc.cnpj LIKE :search)" if search else "1 = 1"

    cnpj_expr = "REPLACE(REPLACE(REPLACE(c.cnpj, '.', ''), '/', ''), '-', '')"
    cc_cnpj_expr = "REPLACE(REPLACE(REPLACE(cc.cnpj, '.', ''), '/', ''), '-', '')"
    dup_check_sql = (
        "SELECT 1 FROM ja_cra_crachas_extratos e "
        "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
        f"WHERE {cnpj_expr} = {cc_cnpj_expr}"
    )

    total = db.session.execute(
        text(
            "SELECT COUNT(*) AS total FROM ("
            "SELECT e.idclientes_fk, e.idprodutos_fk "
            "FROM ja_cra_crachas_extratos e "
            "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
            f"WHERE {where_sql} "
            "GROUP BY e.idclientes_fk, e.idprodutos_fk "
            "UNION ALL "
            "SELECT cc.id AS idclientes_fk, NULL AS idprodutos_fk "
            "FROM controle_de_crachas cc "
            f"WHERE {where_cc_sql} "
            f"AND NOT EXISTS ({dup_check_sql})"
            ") AS totalizador"
        ),
        params,
    ).scalar() or 0

    limit = RESULTS_PER_PAGE
    offset = (page - 1) * limit
    rows = db.session.execute(
        text(
            "SELECT merged.idclientes_fk, merged.nome_fantasia, merged.razao_social, "
            "merged.produto, merged.idprodutos_fk, merged.saldo, merged.tem_extrato "
            "FROM ("
            "SELECT e.idclientes_fk, c.nome_fantasia, c.razao_social, "
            "p.produto, e.idprodutos_fk, "
            "SUM(e.quantidade * e.entrada_saida) AS saldo, "
            "1 AS tem_extrato "
            "FROM ja_cra_crachas_extratos e "
            "INNER JOIN ja_cli_clientes c ON (e.idclientes_fk = c.id_pk) "
            "INNER JOIN ja_pro_produtos p ON (e.idprodutos_fk = p.id_pk) "
            f"WHERE {where_sql} "
            "GROUP BY e.idclientes_fk, c.nome_fantasia, c.razao_social, p.produto, e.idprodutos_fk "
            "UNION ALL "
            "SELECT NULL AS idclientes_fk, cc.cliente AS nome_fantasia, '' AS razao_social, "
            "'Crachás' AS produto, NULL AS idprodutos_fk, "
            "cc.quantidade_em_estoque AS saldo, 0 AS tem_extrato "
            "FROM controle_de_crachas cc "
            f"WHERE {where_cc_sql} "
            f"AND NOT EXISTS ({dup_check_sql})"
            ") AS merged "
            "ORDER BY merged.nome_fantasia "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).fetchall()

    extratos_rows = [dict(row._mapping) for row in rows]
    for row in extratos_rows:
        row["can_lancamentos"] = bool(row.get("tem_extrato")) and bool(row.get("idclientes_fk")) and bool(
            row.get("idprodutos_fk")
        )
    pagination = _paginate(total, page, RESULTS_PER_PAGE)

    clientes = _fetch_clientes()
    produtos = _fetch_produtos()

    return render_template(
        "admin/cracha/extratos.html",
        extratos=extratos_rows,
        pagination=pagination,
        search_value=search,
        clientes=clientes,
        produtos=produtos,
        build_url=lambda **kw: _build_url("cracha_bp.extratos", **kw),
    )


@cracha_bp.route("/extratos/novo", methods=["GET", "POST"])
@login_required
def extratos_novo():
    clientes = _fetch_clientes()
    produtos = _fetch_produtos()

    if request.method == "POST":
        cliente_id = _safe_int(request.form.get("cliente_id"))
        produto_id = _safe_int(request.form.get("produto_id"))
        quantidade = _safe_int(request.form.get("quantidade"))
        data = (request.form.get("data") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()

        if not cliente_id or not produto_id or not quantidade or not data or not descricao:
            flash("Preencha todos os campos obrigatórios.", "warning")
            return redirect(url_for("cracha_bp.extratos"))
        else:
            duplicate = db.session.execute(
                text(
                    "SELECT 1 FROM ja_cra_crachas_extratos "
                    "WHERE idclientes_fk = :cliente AND idprodutos_fk = :produto LIMIT 1"
                ),
                {"cliente": cliente_id, "produto": produto_id},
            ).fetchone()
            if duplicate:
                flash("Já existe um extrato para este cliente e produto.", "warning")
                return redirect(url_for("cracha_bp.extratos"))
            else:
                db.session.execute(
                    text(
                        "INSERT INTO ja_cra_crachas_extratos "
                        "(idclientes_fk, quantidade, entrada_saida, idprodutos_fk, descricao, data) "
                        "VALUES (:cliente, :quantidade, :entrada, :produto, :descricao, :data)"
                    ),
                    {
                        "cliente": cliente_id,
                        "quantidade": quantidade,
                        "entrada": 1,
                        "produto": produto_id,
                        "descricao": descricao,
                        "data": data,
                    },
                )
                db.session.commit()
                flash("Extrato criado.", "success")
                if request.form.get("save_more"):
                    return redirect(url_for("cracha_bp.extratos_novo"))
                return redirect(url_for("cracha_bp.extratos"))

    return render_template(
        "admin/cracha/extratos_form.html",
        clientes=clientes,
        produtos=produtos,
        action_url=url_for("cracha_bp.extratos_novo"),
        allow_save_more=True,
    )


def _build_lancamentos(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lancamentos: list[dict[str, Any]] = []
    saldo = 0
    current_key = None
    current_label = None
    for row in rows:
        data = row.get("data")
        data_key = data if isinstance(data, str) else str(data)
        data_label = _format_date(data)
        if current_key and data_key != current_key:
            lancamentos.append(
                {
                    "tipo": "saldo",
                    "data": current_label,
                    "descricao": "SALDO",
                    "credito_debito": None,
                    "saldo_no_dia": saldo,
                }
            )
        credito_debito = _safe_int(row.get("quantidade")) * _safe_int(row.get("entrada_saida"), 0)
        saldo += credito_debito
        lancamentos.append(
            {
                "tipo": "movimento",
                "data": data_label,
                "descricao": row.get("descricao") or "",
                "credito_debito": credito_debito,
                "saldo_no_dia": None,
            }
        )
        current_key = data_key
        current_label = data_label
    if current_key is not None:
        lancamentos.append(
            {
                "tipo": "saldo",
                "data": current_label,
                "descricao": "SALDO",
                "credito_debito": None,
                "saldo_no_dia": saldo,
            }
        )
    return lancamentos


@cracha_bp.route("/extratos/<int:cliente_id>/<int:produto_id>")
@login_required
def extratos_lancamentos(cliente_id: int, produto_id: int):
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    per_page = 10

    rows = db.session.execute(
        text(
            "SELECT data, descricao, quantidade, entrada_saida "
            "FROM ja_cra_crachas_extratos "
            "WHERE idclientes_fk = :cliente AND idprodutos_fk = :produto "
            "ORDER BY data, id_pk"
        ),
        {"cliente": cliente_id, "produto": produto_id},
    ).fetchall()

    full_lancamentos = _build_lancamentos([dict(row._mapping) for row in rows])

    cliente_row = db.session.execute(
        text("SELECT nome_fantasia, razao_social FROM ja_cli_clientes WHERE id_pk = :id"),
        {"id": cliente_id},
    ).fetchone()
    produto_row = db.session.execute(
        text("SELECT produto FROM ja_pro_produtos WHERE id_pk = :id"),
        {"id": produto_id},
    ).fetchone()

    cliente_nome = cliente_row[0] if cliente_row else ""
    cliente_razao = cliente_row[1] if cliente_row else ""
    produto_nome = produto_row[0] if produto_row else ""

    total_credito = sum(item["credito_debito"] for item in full_lancamentos if item["tipo"] == "movimento" and item["credito_debito"] > 0)
    total_debito = sum(abs(item["credito_debito"]) for item in full_lancamentos if item["tipo"] == "movimento" and item["credito_debito"] < 0)
    saldo_atual = sum(item["credito_debito"] for item in full_lancamentos if item["tipo"] == "movimento")

    total_items = len(full_lancamentos)
    total_pages = (total_items + per_page - 1) // per_page
    offset = (page - 1) * per_page
    paginated_lancamentos = full_lancamentos[offset : offset + per_page]

    return render_template(
        "admin/cracha/extratos_lancamentos.html",
        cliente_id=cliente_id,
        produto_id=produto_id,
        cliente_nome=cliente_nome,
        cliente_razao=cliente_razao,
        produto_nome=produto_nome,
        lancamentos=paginated_lancamentos,
        total_credito=total_credito,
        total_debito=total_debito,
        saldo_atual=saldo_atual,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
    )


@cracha_bp.route("/extratos/lancamentos", methods=["POST"])
@login_required
def extratos_gravar_lancamento():
    cliente_id = _safe_int(request.form.get("cliente_id"))
    produto_id = _safe_int(request.form.get("produto_id"))
    quantidade = _safe_int(request.form.get("quantidade"))
    data = (request.form.get("data") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()
    entrada_saida = _safe_int(request.form.get("entrada_saida"), 0)

    if not cliente_id or not produto_id:
        flash("Cliente ou produto inv\u00e1lido.", "warning")
        return redirect(url_for("cracha_bp.extratos"))
    if not quantidade or not data or not descricao or entrada_saida not in (-1, 1):
        flash("Preencha os campos obrigat\u00f3rios.", "warning")
        return redirect(url_for("cracha_bp.extratos_lancamentos", cliente_id=cliente_id, produto_id=produto_id))

    db.session.execute(
        text(
            "INSERT INTO ja_cra_crachas_extratos "
            "(idclientes_fk, quantidade, entrada_saida, idprodutos_fk, descricao, data) "
            "VALUES (:cliente, :quantidade, :entrada, :produto, :descricao, :data)"
        ),
        {
            "cliente": cliente_id,
            "quantidade": quantidade,
            "entrada": entrada_saida,
            "produto": produto_id,
            "descricao": descricao,
            "data": data,
        },
    )
    db.session.commit()
    flash("Lan\u00e7amento registrado.", "success")
    return redirect(url_for("cracha_bp.extratos_lancamentos", cliente_id=cliente_id, produto_id=produto_id))


@cracha_bp.route("/clientes")
@login_required
def clientes():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append(
            "(nome_fantasia LIKE :search OR razao_social LIKE :search OR cnpj LIKE :search OR cpf LIKE :search)"
        )
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(f"SELECT COUNT(*) AS total FROM ja_cli_clientes WHERE {where_sql}"),
        params,
    ).scalar() or 0
    total_ativos = db.session.execute(
        text(f"SELECT COUNT(*) AS total FROM ja_cli_clientes WHERE {where_sql} AND ativo = 1"),
        params,
    ).scalar() or 0

    rows = db.session.execute(
        text(
            "SELECT id_pk, nome_fantasia, razao_social, cnpj, cpf, ativo "
            f"FROM ja_cli_clientes WHERE {where_sql} "
            "ORDER BY nome_fantasia "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()
    clientes_rows: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        data["ativo"] = bool(data.get("ativo"))
        clientes_rows.append(data)

    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/cracha/clientes.html",
        clientes=clientes_rows,
        search=search,
        pagination=pagination,
        total_ativos=total_ativos,
        build_url=_build_url,
        ufs=_fetch_ufs(),
        localidades=_fetch_localidades(),
        empresas=_fetch_empresas(),
    )


def _load_cliente_with_user(cliente_id: int) -> dict[str, Any] | None:
    row = db.session.execute(
        text(
            "SELECT c.*, "
            "u.id_pk AS id_pkusuario, u.nome AS nomeusuario, "
            "u.login AS loginusuario, u.email AS emailusuario, "
            "u.senha AS senhausuario, u.senha2 AS senha2usuario "
            "FROM ja_cli_clientes c "
            "LEFT JOIN ja_usr_usuarios u ON (c.id_pk = u.idclientes_fk) "
            "WHERE c.id_pk = :id"
        ),
        {"id": cliente_id},
    ).fetchone()
    return dict(row._mapping) if row else None


def _hash_password(raw: str, user_id: int) -> str:
    return hashlib.md5(f"{raw}{user_id}".encode("utf-8")).hexdigest()


@cracha_bp.route("/clientes/novo", methods=["GET", "POST"])
@login_required
def clientes_novo():
    if request.method == "POST":
        nome_fantasia = (request.form.get("txtNomeFantasia") or "").strip()
        razao_social = (request.form.get("txtRazaoSocial") or "").strip()
        tipo = _safe_int(request.form.get("radTipo"), 2) or 2
        ativo = _bool_from_form(request.form.get("radAtivo") or "t")
        idlocalidade = _parse_int(request.form.get("selLocalidade"))
        idempresa = _parse_int(request.form.get("selEmpresa"))

        nome_usuario = (request.form.get("txtNomeUsuario") or "").strip()
        login_usuario = (request.form.get("txtLoginUsuario") or "").strip()
        senha_usuario = (request.form.get("txtSenhaUsuario") or "").strip()
        email_usuario = (request.form.get("txtEmailUsuario") or "").strip()
        senha2_raw = (request.form.get("txtCNPJSenha2") or "").strip()

        if not nome_fantasia or not idlocalidade or not idempresa:
            flash("Preencha nome fantasia, localidade e empresa.", "warning")
        elif not nome_usuario or not login_usuario or not senha_usuario or not email_usuario:
            flash("Preencha os dados do usu\u00e1rio do cliente.", "warning")
        else:
            try:
                cliente_id = _next_id("ja_cli_clientes")
                db.session.execute(
                    text(
                        "INSERT INTO ja_cli_clientes "
                        "(id_pk, nome_fantasia, razao_social, cnpj, cpf, inscricao_estadual, rg, "
                        "telefone1, telefone2, telefone3, telefone4, email, website, endereco, endereco_numero, "
                        "endereco_complemento, endereco_bairro, endereco_municipio, endereco_uf, endereco_cep, fax, "
                        "tipo, ativo, idlocalidades_fk, contato, contato_setor, idempresas_fk) "
                        "VALUES (:id_pk, :nome_fantasia, :razao_social, :cnpj, :cpf, :inscricao_estadual, :rg, "
                        ":telefone1, :telefone2, :telefone3, :telefone4, :email, :website, :endereco, "
                        ":endereco_numero, :endereco_complemento, :endereco_bairro, :endereco_municipio, "
                        ":endereco_uf, :endereco_cep, :fax, :tipo, :ativo, :idlocalidades_fk, :contato, "
                        ":contato_setor, :idempresas_fk)"
                    ),
                    {
                        "id_pk": cliente_id,
                        "nome_fantasia": nome_fantasia,
                        "razao_social": razao_social or None,
                        "cnpj": re.sub(r"\D+", "", (request.form.get("txtCNPJ") or "").strip()) or None,
                        "cpf": (request.form.get("txtCPF") or "").strip() or None,
                        "inscricao_estadual": (request.form.get("txtInscricaoEstadual") or "").strip() or None,
                        "rg": (request.form.get("txtRG") or "").strip() or None,
                        "telefone1": (request.form.get("txtTelefone1") or "").strip() or None,
                        "telefone2": (request.form.get("txtTelefone2") or "").strip() or None,
                        "telefone3": (request.form.get("txtTelefone3") or "").strip() or None,
                        "telefone4": (request.form.get("txtTelefone4") or "").strip() or None,
                        "email": (request.form.get("txtEmail") or "").strip() or None,
                        "website": (request.form.get("txtWebSite") or "").strip() or None,
                        "endereco": (request.form.get("txtEndereco") or "").strip() or None,
                        "endereco_numero": (request.form.get("txtEnderecoNumero") or "").strip() or None,
                        "endereco_complemento": (request.form.get("txtEnderecoComplemento") or "").strip() or None,
                        "endereco_bairro": (request.form.get("txtEnderecoBairro") or "").strip() or None,
                        "endereco_municipio": (request.form.get("txtEnderecoMunicipio") or "").strip() or None,
                        "endereco_uf": (request.form.get("selUFS") or "").strip() or None,
                        "endereco_cep": (request.form.get("txtEnderecoCEP") or "").strip() or None,
                        "fax": (request.form.get("txtFAX") or "").strip() or None,
                        "tipo": tipo,
                        "ativo": ativo,
                        "idlocalidades_fk": idlocalidade,
                        "contato": (request.form.get("txtContato") or "").strip() or None,
                        "contato_setor": (request.form.get("txtContatoSetor") or "").strip() or None,
                        "idempresas_fk": idempresa,
                    },
                )

                usuario_id = _next_id("ja_usr_usuarios")
                senha_hash = _hash_password(senha_usuario, usuario_id)
                senha2_hash = hashlib.md5(senha2_raw.encode("utf-8")).hexdigest() if senha2_raw else None
                db.session.execute(
                    text(
                        "INSERT INTO ja_usr_usuarios "
                        "(id_pk, nome, login, senha, email, idclientes_fk, ativo, senha2) "
                        "VALUES (:id_pk, :nome, :login, :senha, :email, :idclientes_fk, :ativo, :senha2)"
                    ),
                    {
                        "id_pk": usuario_id,
                        "nome": nome_usuario,
                        "login": login_usuario,
                        "senha": senha_hash,
                        "email": email_usuario,
                        "idclientes_fk": cliente_id,
                        "ativo": ativo,
                        "senha2": senha2_hash,
                    },
                )
                db.session.commit()

                if request.form.get("save_more"):
                    flash("Cliente salvo. Voc\u00ea pode cadastrar outro.", "success")
                    return redirect(url_for("cracha_bp.clientes_novo"))
                flash("Cliente cadastrado com sucesso.", "success")
                return redirect(url_for("cracha_bp.clientes"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao cadastrar cliente legado")
                flash("Erro ao salvar cliente.", "danger")

    return render_template(
        "admin/cracha/clientes_form.html",
        cliente=None,
        ufs=_fetch_ufs(),
        localidades=_fetch_localidades(),
        empresas=_fetch_empresas(),
        action_url=url_for("cracha_bp.clientes_novo"),
        back_url=url_for("cracha_bp.clientes"),
        allow_more=True,
        subtitle="Cadastre um novo cliente com as informa\u00e7\u00f5es completas.",
    )


@cracha_bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def clientes_editar(cliente_id: int):
    cliente = _load_cliente_with_user(cliente_id)
    if not cliente:
        flash("Cliente n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.clientes"))

    if request.method == "POST":
        nome_fantasia = (request.form.get("txtNomeFantasia") or "").strip()
        razao_social = (request.form.get("txtRazaoSocial") or "").strip()
        tipo = _safe_int(request.form.get("radTipo"), 2) or 2
        ativo = _bool_from_form(request.form.get("radAtivo") or "t")
        idlocalidade = _parse_int(request.form.get("selLocalidade"))
        idempresa = _parse_int(request.form.get("selEmpresa"))

        nome_usuario = (request.form.get("txtNomeUsuario") or "").strip()
        login_usuario = (request.form.get("txtLoginUsuario") or "").strip()
        senha_usuario = (request.form.get("txtSenhaUsuario") or "").strip()
        email_usuario = (request.form.get("txtEmailUsuario") or "").strip()
        senha2_raw = (request.form.get("txtCNPJSenha2") or "").strip()

        if not nome_fantasia or not idlocalidade or not idempresa:
            flash("Preencha nome fantasia, localidade e empresa.", "warning")
        elif not nome_usuario or not login_usuario or not email_usuario:
            flash("Preencha os dados do usu\u00e1rio do cliente.", "warning")
        else:
            try:
                db.session.execute(
                    text(
                        "UPDATE ja_cli_clientes SET "
                        "nome_fantasia = :nome_fantasia, razao_social = :razao_social, cnpj = :cnpj, "
                        "cpf = :cpf, inscricao_estadual = :inscricao_estadual, rg = :rg, telefone1 = :telefone1, "
                        "telefone2 = :telefone2, telefone3 = :telefone3, telefone4 = :telefone4, email = :email, "
                        "website = :website, endereco = :endereco, endereco_numero = :endereco_numero, "
                        "endereco_complemento = :endereco_complemento, endereco_bairro = :endereco_bairro, "
                        "endereco_municipio = :endereco_municipio, endereco_uf = :endereco_uf, "
                        "endereco_cep = :endereco_cep, fax = :fax, tipo = :tipo, ativo = :ativo, "
                        "idlocalidades_fk = :idlocalidades_fk, contato = :contato, contato_setor = :contato_setor, "
                        "idempresas_fk = :idempresas_fk "
                        "WHERE id_pk = :id_pk"
                    ),
                    {
                        "id_pk": cliente_id,
                        "nome_fantasia": nome_fantasia,
                        "razao_social": razao_social or None,
                        "cnpj": re.sub(r"\D+", "", (request.form.get("txtCNPJ") or "").strip()) or None,
                        "cpf": (request.form.get("txtCPF") or "").strip() or None,
                        "inscricao_estadual": (request.form.get("txtInscricaoEstadual") or "").strip() or None,
                        "rg": (request.form.get("txtRG") or "").strip() or None,
                        "telefone1": (request.form.get("txtTelefone1") or "").strip() or None,
                        "telefone2": (request.form.get("txtTelefone2") or "").strip() or None,
                        "telefone3": (request.form.get("txtTelefone3") or "").strip() or None,
                        "telefone4": (request.form.get("txtTelefone4") or "").strip() or None,
                        "email": (request.form.get("txtEmail") or "").strip() or None,
                        "website": (request.form.get("txtWebSite") or "").strip() or None,
                        "endereco": (request.form.get("txtEndereco") or "").strip() or None,
                        "endereco_numero": (request.form.get("txtEnderecoNumero") or "").strip() or None,
                        "endereco_complemento": (request.form.get("txtEnderecoComplemento") or "").strip()
                        or None,
                        "endereco_bairro": (request.form.get("txtEnderecoBairro") or "").strip() or None,
                        "endereco_municipio": (request.form.get("txtEnderecoMunicipio") or "").strip() or None,
                        "endereco_uf": (request.form.get("selUFS") or "").strip() or None,
                        "endereco_cep": (request.form.get("txtEnderecoCEP") or "").strip() or None,
                        "fax": (request.form.get("txtFAX") or "").strip() or None,
                        "tipo": tipo,
                        "ativo": ativo,
                        "idlocalidades_fk": idlocalidade,
                        "contato": (request.form.get("txtContato") or "").strip() or None,
                        "contato_setor": (request.form.get("txtContatoSetor") or "").strip() or None,
                        "idempresas_fk": idempresa,
                    },
                )

                usuario_id = _parse_int(request.form.get("txtIDUsuario"))
                if usuario_id:
                    existing_user = db.session.execute(
                        text("SELECT senha, senha2 FROM ja_usr_usuarios WHERE id_pk = :id"),
                        {"id": usuario_id},
                    ).fetchone()
                    senha_hash = existing_user[0] if existing_user else None
                    senha2_hash = existing_user[1] if existing_user else None
                    if senha_usuario:
                        senha_hash = _hash_password(senha_usuario, usuario_id)
                    if senha2_raw:
                        senha2_hash = hashlib.md5(senha2_raw.encode("utf-8")).hexdigest()
                    db.session.execute(
                        text(
                            "UPDATE ja_usr_usuarios SET "
                            "nome = :nome, login = :login, senha = :senha, email = :email, ativo = :ativo, "
                            "senha2 = :senha2 "
                            "WHERE id_pk = :id_pk"
                        ),
                        {
                            "id_pk": usuario_id,
                            "nome": nome_usuario,
                            "login": login_usuario,
                            "senha": senha_hash,
                            "email": email_usuario,
                            "ativo": ativo,
                            "senha2": senha2_hash,
                        },
                    )
                else:
                    usuario_id = _next_id("ja_usr_usuarios")
                    senha_hash = _hash_password(senha_usuario, usuario_id) if senha_usuario else None
                    senha2_hash = hashlib.md5(senha2_raw.encode("utf-8")).hexdigest() if senha2_raw else None
                    db.session.execute(
                        text(
                            "INSERT INTO ja_usr_usuarios "
                            "(id_pk, nome, login, senha, email, idclientes_fk, ativo, senha2) "
                            "VALUES (:id_pk, :nome, :login, :senha, :email, :idclientes_fk, :ativo, :senha2)"
                        ),
                        {
                            "id_pk": usuario_id,
                            "nome": nome_usuario,
                            "login": login_usuario,
                            "senha": senha_hash,
                            "email": email_usuario,
                            "idclientes_fk": cliente_id,
                            "ativo": ativo,
                            "senha2": senha2_hash,
                        },
                    )

                db.session.commit()
                flash("Cliente atualizado com sucesso.", "success")
                return redirect(url_for("cracha_bp.clientes"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar cliente legado")
                flash("Erro ao atualizar cliente.", "danger")

    return render_template(
        "admin/cracha/clientes_form.html",
        cliente=cliente,
        ufs=_fetch_ufs(),
        localidades=_fetch_localidades(),
        empresas=_fetch_empresas(),
        action_url=url_for("cracha_bp.clientes_editar", cliente_id=cliente_id),
        back_url=url_for("cracha_bp.clientes"),
        allow_more=False,
        subtitle="Atualize os dados e contatos do cliente.",
    )


@cracha_bp.route("/clientes/<int:cliente_id>/excluir", methods=["POST"])
@login_required
def clientes_excluir(cliente_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_cli_clientes WHERE id_pk = :id"),
            {"id": cliente_id},
        )
        db.session.commit()
        flash("Cliente removido.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir cliente legado")
        flash("Erro ao excluir cliente.", "danger")
    return redirect(url_for("cracha_bp.clientes"))


@cracha_bp.route("/empresas")
@login_required
def empresas():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("nome LIKE :search")
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(f"SELECT COUNT(*) AS total FROM ja_emp_empresas WHERE {where_sql}"),
        params,
    ).scalar() or 0
    rows = db.session.execute(
        text(
            "SELECT id_pk, nome, ativo FROM ja_emp_empresas "
            f"WHERE {where_sql} ORDER BY nome LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()
    empresas_rows = [dict(row._mapping) for row in rows]
    for row in empresas_rows:
        row["ativo"] = bool(row.get("ativo"))
    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/cracha/empresas.html",
        empresas=empresas_rows,
        search=search,
        pagination=pagination,
        build_url=_build_url,
    )


@cracha_bp.route("/empresas/novo", methods=["GET", "POST"])
@login_required
def empresas_novo():
    origin = request.form.get("origin") if request.method == "POST" else None
    if request.method == "POST":
        nome = (request.form.get("txtNome") or "").strip()
        ativo = _bool_from_form(request.form.get("ativo") or "1")
        if not nome:
            flash("Informe o nome da empresa.", "warning")
            if origin == "list":
                return redirect(url_for("cracha_bp.empresas"))
        else:
            try:
                empresa_id = _next_id("ja_emp_empresas")
                db.session.execute(
                    text("INSERT INTO ja_emp_empresas (id_pk, nome, ativo) VALUES (:id, :nome, :ativo)"),
                    {"id": empresa_id, "nome": nome, "ativo": ativo},
                )
                db.session.commit()
                if request.form.get("save_more"):
                    flash("Empresa salva. Voc\u00ea pode cadastrar outra.", "success")
                    if origin == "list":
                        return redirect(url_for("cracha_bp.empresas"))
                    return redirect(url_for("cracha_bp.empresas_novo"))
                flash("Empresa cadastrada.", "success")
                return redirect(url_for("cracha_bp.empresas"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao criar empresa")
                flash("Erro ao salvar empresa.", "danger")
                if origin == "list":
                    return redirect(url_for("cracha_bp.empresas"))

    return render_template(
        "admin/cracha/empresas_form.html",
        empresa=None,
        action_url=url_for("cracha_bp.empresas_novo"),
        back_url=url_for("cracha_bp.empresas"),
        allow_more=True,
        subtitle="Cadastre uma nova empresa.",
    )


@cracha_bp.route("/empresas/<int:empresa_id>/editar", methods=["GET", "POST"])
@login_required
def empresas_editar(empresa_id: int):
    row = db.session.execute(
        text("SELECT id_pk, nome, ativo FROM ja_emp_empresas WHERE id_pk = :id"),
        {"id": empresa_id},
    ).fetchone()
    if not row:
        flash("Empresa n\u00e3o encontrada.", "warning")
        return redirect(url_for("cracha_bp.empresas"))
    empresa = dict(row._mapping)
    empresa["ativo"] = bool(empresa.get("ativo"))

    if request.method == "POST":
        nome = (request.form.get("txtNome") or "").strip()
        ativo = _bool_from_form(request.form.get("ativo") or "1")
        if not nome:
            flash("Informe o nome da empresa.", "warning")
        else:
            try:
                db.session.execute(
                    text("UPDATE ja_emp_empresas SET nome = :nome, ativo = :ativo WHERE id_pk = :id"),
                    {"id": empresa_id, "nome": nome, "ativo": ativo},
                )
                db.session.commit()
                flash("Empresa atualizada.", "success")
                return redirect(url_for("cracha_bp.empresas"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar empresa")
                flash("Erro ao atualizar empresa.", "danger")

    return render_template(
        "admin/cracha/empresas_form.html",
        empresa=empresa,
        action_url=url_for("cracha_bp.empresas_editar", empresa_id=empresa_id),
        back_url=url_for("cracha_bp.empresas"),
        allow_more=False,
        subtitle="Atualize os dados da empresa.",
    )


@cracha_bp.route("/empresas/<int:empresa_id>/excluir", methods=["POST"])
@login_required
def empresas_excluir(empresa_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_emp_empresas WHERE id_pk = :id"),
            {"id": empresa_id},
        )
        db.session.commit()
        flash("Empresa removida.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir empresa")
        flash("Erro ao excluir empresa.", "danger")
    return redirect(url_for("cracha_bp.empresas"))


@cracha_bp.route("/fornecedor")
@login_required
def fornecedor():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("nome LIKE :search")
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(f"SELECT COUNT(*) AS total FROM ja_pro_fornecedor WHERE {where_sql}"),
        params,
    ).scalar() or 0
    rows = db.session.execute(
        text(
            "SELECT id_pk, nome, ativo FROM ja_pro_fornecedor "
            f"WHERE {where_sql} ORDER BY nome LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()
    fornecedores_rows = [dict(row._mapping) for row in rows]
    for row in fornecedores_rows:
        row["ativo"] = bool(row.get("ativo"))
    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/cracha/fornecedor.html",
        fornecedores=fornecedores_rows,
        search=search,
        pagination=pagination,
        build_url=_build_url,
    )


@cracha_bp.route("/fornecedor/novo", methods=["GET", "POST"])
@login_required
def fornecedor_novo():
    origin = request.form.get("origin") if request.method == "POST" else None
    if request.method == "POST":
        nome = (request.form.get("txtNome") or "").strip()
        ativo = _bool_from_form(request.form.get("ativo") or "1")
        if not nome:
            flash("Informe o nome do fornecedor.", "warning")
            if origin == "list":
                return redirect(url_for("cracha_bp.fornecedor"))
        else:
            try:
                fornecedor_id = _next_id("ja_pro_fornecedor")
                db.session.execute(
                    text("INSERT INTO ja_pro_fornecedor (id_pk, nome, ativo) VALUES (:id, :nome, :ativo)"),
                    {"id": fornecedor_id, "nome": nome, "ativo": ativo},
                )
                db.session.commit()
                if request.form.get("save_more"):
                    flash("Fornecedor salvo. Voc\u00ea pode cadastrar outro.", "success")
                    if origin == "list":
                        return redirect(url_for("cracha_bp.fornecedor"))
                    return redirect(url_for("cracha_bp.fornecedor_novo"))
                flash("Fornecedor cadastrado.", "success")
                return redirect(url_for("cracha_bp.fornecedor"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao criar fornecedor")
                flash("Erro ao salvar fornecedor.", "danger")
                if origin == "list":
                    return redirect(url_for("cracha_bp.fornecedor"))

    return render_template(
        "admin/cracha/fornecedor_form.html",
        fornecedor=None,
        action_url=url_for("cracha_bp.fornecedor_novo"),
        back_url=url_for("cracha_bp.fornecedor"),
        allow_more=True,
        subtitle="Cadastre um novo fornecedor.",
    )


@cracha_bp.route("/fornecedor/<int:fornecedor_id>/editar", methods=["GET", "POST"])
@login_required
def fornecedor_editar(fornecedor_id: int):
    row = db.session.execute(
        text("SELECT id_pk, nome, ativo FROM ja_pro_fornecedor WHERE id_pk = :id"),
        {"id": fornecedor_id},
    ).fetchone()
    if not row:
        flash("Fornecedor n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.fornecedor"))
    fornecedor_row = dict(row._mapping)
    fornecedor_row["ativo"] = bool(fornecedor_row.get("ativo"))

    if request.method == "POST":
        nome = (request.form.get("txtNome") or "").strip()
        ativo = _bool_from_form(request.form.get("ativo") or "1")
        if not nome:
            flash("Informe o nome do fornecedor.", "warning")
        else:
            try:
                db.session.execute(
                    text("UPDATE ja_pro_fornecedor SET nome = :nome, ativo = :ativo WHERE id_pk = :id"),
                    {"id": fornecedor_id, "nome": nome, "ativo": ativo},
                )
                db.session.commit()
                flash("Fornecedor atualizado.", "success")
                return redirect(url_for("cracha_bp.fornecedor"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar fornecedor")
                flash("Erro ao atualizar fornecedor.", "danger")

    return render_template(
        "admin/cracha/fornecedor_form.html",
        fornecedor=fornecedor_row,
        action_url=url_for("cracha_bp.fornecedor_editar", fornecedor_id=fornecedor_id),
        back_url=url_for("cracha_bp.fornecedor"),
        allow_more=False,
        subtitle="Atualize o cadastro do fornecedor.",
    )


@cracha_bp.route("/fornecedor/<int:fornecedor_id>/excluir", methods=["POST"])
@login_required
def fornecedor_excluir(fornecedor_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_pro_fornecedor WHERE id_pk = :id"),
            {"id": fornecedor_id},
        )
        db.session.commit()
        flash("Fornecedor removido.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir fornecedor")
        flash("Erro ao excluir fornecedor.", "danger")
    return redirect(url_for("cracha_bp.fornecedor"))


def _load_produto_detalhes(produto_id: int | None) -> list[dict[str, Any]]:
    empresas = _fetch_empresas()
    detalhes_map: dict[int, dict[str, Any]] = {}
    if produto_id:
        rows = db.session.execute(
            text("SELECT * FROM ja_pro_produtos_detalhe WHERE idprodutos_fk = :id"),
            {"id": produto_id},
        ).fetchall()
        for row in rows:
            data = dict(row._mapping)
            detalhes_map[int(data.get("idempresas_fk"))] = data

    detalhes: list[dict[str, Any]] = []
    for empresa in empresas:
        det = detalhes_map.get(int(empresa["id_pk"])) or {}
        detalhes.append(
            {
                "empresa_id": empresa["id_pk"],
                "empresa_nome": empresa["nome"],
                "id_pk": det.get("id_pk"),
                "quantidade_minima": det.get("quantidade_minima"),
                "quantidade_maxima": det.get("quantidade_maxima"),
                "corredor": det.get("corredor"),
                "prateleira": det.get("prateleira"),
                "gaveta": det.get("gaveta"),
                "quantidade_atual": det.get("quantidade_atual"),
                "armario": det.get("armario"),
                "palete": det.get("palete"),
                "ativo": bool(det.get("ativo")) if det else False,
            }
        )
    return detalhes


def _save_produto_detalhes(produto_id: int, form: dict[str, Any]) -> None:
    pattern = re.compile(r"^txtEstoqueMinimo\\[(\\d+)\\]$")
    empresas_ids: list[int] = []
    for key in form.keys():
        match = pattern.match(key)
        if match:
            empresas_ids.append(int(match.group(1)))
    for empresa_id in empresas_ids:
        detalhe_id = _parse_int(form.get(f"txtIDProdutoDetalhe[{empresa_id}]"))
        data = {
            "quantidade_minima": _parse_int(form.get(f"txtEstoqueMinimo[{empresa_id}]")),
            "quantidade_maxima": _parse_int(form.get(f"txtEstoqueMaximo[{empresa_id}]")),
            "corredor": (form.get(f"txtEstoqueCorredor[{empresa_id}]") or "").strip() or None,
            "prateleira": (form.get(f"txtEstoquePrateleira[{empresa_id}]") or "").strip() or None,
            "gaveta": (form.get(f"txtEstoqueGaveta[{empresa_id}]") or "").strip() or None,
            "armario": (form.get(f"txtEstoqueArmario[{empresa_id}]") or "").strip() or None,
            "palete": (form.get(f"txtEstoquePalete[{empresa_id}]") or "").strip() or None,
            "quantidade_atual": _parse_int(form.get(f"txtEstoqueQuantidadeAtual[{empresa_id}]")),
            "ativo": 1 if form.get(f"chkAtivo[{empresa_id}]") else 0,
        }

        if detalhe_id:
            db.session.execute(
                text(
                    "UPDATE ja_pro_produtos_detalhe SET "
                    "quantidade_minima = :quantidade_minima, quantidade_maxima = :quantidade_maxima, "
                    "ativo = :ativo, corredor = :corredor, prateleira = :prateleira, gaveta = :gaveta, "
                    "quantidade_atual = :quantidade_atual, armario = :armario, palete = :palete "
                    "WHERE id_pk = :id_pk"
                ),
                {"id_pk": detalhe_id, **data},
            )
        else:
            new_id = _next_id("ja_pro_produtos_detalhe")
            db.session.execute(
                text(
                    "INSERT INTO ja_pro_produtos_detalhe "
                    "(id_pk, idprodutos_fk, quantidade_minima, quantidade_maxima, ativo, idempresas_fk, "
                    "corredor, prateleira, gaveta, quantidade_atual, armario, palete) "
                    "VALUES (:id_pk, :idprodutos_fk, :quantidade_minima, :quantidade_maxima, :ativo, :idempresas_fk, "
                    ":corredor, :prateleira, :gaveta, :quantidade_atual, :armario, :palete)"
                ),
                {
                    "id_pk": new_id,
                    "idprodutos_fk": produto_id,
                    "idempresas_fk": empresa_id,
                    **data,
                },
            )


@cracha_bp.route("/produtos")
@login_required
def produtos():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if search:
        where.append("(produto LIKE :search OR codigo LIKE :search)")
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(f"SELECT COUNT(*) AS total FROM ja_pro_produtos WHERE {where_sql}"),
        params,
    ).scalar() or 0
    rows = db.session.execute(
        text(
            "SELECT id_pk, produto, codigo, controlado_numero_serie "
            f"FROM ja_pro_produtos WHERE {where_sql} "
            "ORDER BY produto LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()
    produtos_rows = [dict(row._mapping) for row in rows]
    for row in produtos_rows:
        row["controlado_numero_serie"] = bool(row.get("controlado_numero_serie"))
    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/cracha/produtos.html",
        produtos=produtos_rows,
        grupos=_fetch_grupos(),
        marcas=_fetch_marcas(),
        detalhes=_load_produto_detalhes(None),
        search=search,
        pagination=pagination,
        build_url=_build_url,
    )


@cracha_bp.route("/produtos/novo", methods=["GET", "POST"])
@login_required
def produtos_novo():
    origin = request.form.get("origin") if request.method == "POST" else None
    if request.method == "POST":
        codigo = (request.form.get("txtCodigoProduto") or "").strip()
        produto_nome = (request.form.get("txtProduto") or "").strip()
        if not codigo or not produto_nome:
            flash("Preencha c\u00f3digo e produto.", "warning")
            if origin == "list":
                return redirect(url_for("cracha_bp.produtos"))
        else:
            try:
                produto_id = _next_id("ja_pro_produtos")
                db.session.execute(
                    text(
                        "INSERT INTO ja_pro_produtos "
                        "(id_pk, produto, codigo, controlado_numero_serie, observacoes, "
                        "idprodutos_grupo_fk, idprodutos_marca_fk, codigo_marca) "
                        "VALUES (:id_pk, :produto, :codigo, :controlado, :observacoes, :grupo, :marca, :codigo_marca)"
                    ),
                    {
                        "id_pk": produto_id,
                        "produto": produto_nome,
                        "codigo": codigo,
                        "controlado": 1 if request.form.get("chkControledoPorNumeroDeSerie") else 0,
                        "observacoes": (request.form.get("txtObservacoes") or "").strip() or None,
                        "grupo": _parse_int(request.form.get("selGrupo")),
                        "marca": _parse_int(request.form.get("selMarca")),
                        "codigo_marca": (request.form.get("txtCodigoMarca") or "").strip() or None,
                    },
                )
                _save_produto_detalhes(produto_id, request.form)
                db.session.commit()
                if request.form.get("save_more"):
                    flash("Produto salvo. Voc\u00ea pode cadastrar outro.", "success")
                    if origin == "list":
                        return redirect(url_for("cracha_bp.produtos"))
                    return redirect(url_for("cracha_bp.produtos_novo"))
                flash("Produto cadastrado.", "success")
                return redirect(url_for("cracha_bp.produtos"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao criar produto")
                flash("Erro ao salvar produto.", "danger")
                if origin == "list":
                    return redirect(url_for("cracha_bp.produtos"))

    return render_template(
        "admin/cracha/produtos_form.html",
        produto=None,
        grupos=_fetch_grupos(),
        marcas=_fetch_marcas(),
        detalhes=_load_produto_detalhes(None),
        action_url=url_for("cracha_bp.produtos_novo"),
        back_url=url_for("cracha_bp.produtos"),
        allow_more=True,
        subtitle="Cadastre um novo produto.",
    )


@cracha_bp.route("/produtos/<int:produto_id>/editar", methods=["GET", "POST"])
@login_required
def produtos_editar(produto_id: int):
    produto_row = db.session.execute(
        text("SELECT * FROM ja_pro_produtos WHERE id_pk = :id"),
        {"id": produto_id},
    ).fetchone()
    if not produto_row:
        flash("Produto n\u00e3o encontrado.", "warning")
        return redirect(url_for("cracha_bp.produtos"))
    produto = dict(produto_row._mapping)

    if request.method == "POST":
        codigo = (request.form.get("txtCodigoProduto") or "").strip()
        produto_nome = (request.form.get("txtProduto") or "").strip()
        if not codigo or not produto_nome:
            flash("Preencha c\u00f3digo e produto.", "warning")
        else:
            try:
                db.session.execute(
                    text(
                        "UPDATE ja_pro_produtos SET "
                        "produto = :produto, codigo = :codigo, controlado_numero_serie = :controlado, "
                        "observacoes = :observacoes, idprodutos_grupo_fk = :grupo, idprodutos_marca_fk = :marca, "
                        "codigo_marca = :codigo_marca "
                        "WHERE id_pk = :id_pk"
                    ),
                    {
                        "id_pk": produto_id,
                        "produto": produto_nome,
                        "codigo": codigo,
                        "controlado": 1 if request.form.get("chkControledoPorNumeroDeSerie") else 0,
                        "observacoes": (request.form.get("txtObservacoes") or "").strip() or None,
                        "grupo": _parse_int(request.form.get("selGrupo")),
                        "marca": _parse_int(request.form.get("selMarca")),
                        "codigo_marca": (request.form.get("txtCodigoMarca") or "").strip() or None,
                    },
                )
                _save_produto_detalhes(produto_id, request.form)
                db.session.commit()
                flash("Produto atualizado.", "success")
                return redirect(url_for("cracha_bp.produtos"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar produto")
                flash("Erro ao atualizar produto.", "danger")

    return render_template(
        "admin/cracha/produtos_form.html",
        produto=produto,
        grupos=_fetch_grupos(),
        marcas=_fetch_marcas(),
        detalhes=_load_produto_detalhes(produto_id),
        action_url=url_for("cracha_bp.produtos_editar", produto_id=produto_id),
        back_url=url_for("cracha_bp.produtos"),
        allow_more=False,
        subtitle="Atualize os dados do produto.",
    )


@cracha_bp.route("/produtos/<int:produto_id>/excluir", methods=["POST"])
@login_required
def produtos_excluir(produto_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_pro_produtos_detalhe WHERE idprodutos_fk = :id"),
            {"id": produto_id},
        )
        db.session.execute(
            text("DELETE FROM ja_pro_produtos WHERE id_pk = :id"),
            {"id": produto_id},
        )
        db.session.commit()
        flash("Produto removido.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir produto")
        flash("Erro ao excluir produto.", "danger")
    return redirect(url_for("cracha_bp.produtos"))


@cracha_bp.route("/produtos/grupo", methods=["GET", "POST"])
@login_required
def produtos_grupo():
    edit_id = _parse_int(request.args.get("edit"))
    grupo = None

    if request.method == "POST":
        nome = (request.form.get("txtGrupo") or "").strip()
        ativo = 1 if request.form.get("chkAtivo") else 0
        grupo_id = _parse_int(request.form.get("txtID"))
        if not nome:
            flash("Informe o nome do grupo.", "warning")
        else:
            try:
                if grupo_id:
                    db.session.execute(
                        text("UPDATE ja_pro_produtos_grupo SET nome = :nome, ativo = :ativo WHERE id_pk = :id"),
                        {"id": grupo_id, "nome": nome, "ativo": ativo},
                    )
                    flash("Grupo atualizado.", "success")
                else:
                    grupo_id = _next_id("ja_pro_produtos_grupo")
                    db.session.execute(
                        text("INSERT INTO ja_pro_produtos_grupo (id_pk, nome, ativo) VALUES (:id, :nome, :ativo)"),
                        {"id": grupo_id, "nome": nome, "ativo": ativo},
                    )
                    flash("Grupo cadastrado.", "success")
                db.session.commit()
                return redirect(url_for("cracha_bp.produtos_grupo"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao salvar grupo")
                flash("Erro ao salvar grupo.", "danger")

    if edit_id:
        row = db.session.execute(
            text("SELECT id_pk, nome, ativo FROM ja_pro_produtos_grupo WHERE id_pk = :id"),
            {"id": edit_id},
        ).fetchone()
        if row:
            grupo = dict(row._mapping)
            grupo["ativo"] = bool(grupo.get("ativo"))

    grupos = _fetch_grupos()
    return render_template(
        "admin/cracha/produtos_grupo.html",
        grupos=grupos,
        grupo=grupo,
        form_action=url_for("cracha_bp.produtos_grupo"),
    )


@cracha_bp.route("/produtos/grupo/<int:grupo_id>/excluir", methods=["POST"])
@login_required
def produtos_grupo_excluir(grupo_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_pro_produtos_grupo WHERE id_pk = :id"),
            {"id": grupo_id},
        )
        db.session.commit()
        flash("Grupo removido.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir grupo")
        flash("Erro ao excluir grupo.", "danger")
    return redirect(url_for("cracha_bp.produtos_grupo"))


@cracha_bp.route("/produtos/marca", methods=["GET", "POST"])
@login_required
def produtos_marca():
    edit_id = _parse_int(request.args.get("edit"))
    marca = None

    if request.method == "POST":
        nome = (request.form.get("txtMarca") or "").strip()
        ativo = 1 if request.form.get("chkAtivo") else 0
        marca_id = _parse_int(request.form.get("txtID"))
        if not nome:
            flash("Informe o nome da marca.", "warning")
        else:
            try:
                if marca_id:
                    db.session.execute(
                        text("UPDATE ja_pro_produtos_marca SET nome = :nome, ativo = :ativo WHERE id_pk = :id"),
                        {"id": marca_id, "nome": nome, "ativo": ativo},
                    )
                    flash("Marca atualizada.", "success")
                else:
                    marca_id = _next_id("ja_pro_produtos_marca")
                    db.session.execute(
                        text("INSERT INTO ja_pro_produtos_marca (id_pk, nome, ativo) VALUES (:id, :nome, :ativo)"),
                        {"id": marca_id, "nome": nome, "ativo": ativo},
                    )
                    flash("Marca cadastrada.", "success")
                db.session.commit()
                return redirect(url_for("cracha_bp.produtos_marca"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao salvar marca")
                flash("Erro ao salvar marca.", "danger")

    if edit_id:
        row = db.session.execute(
            text("SELECT id_pk, nome, ativo FROM ja_pro_produtos_marca WHERE id_pk = :id"),
            {"id": edit_id},
        ).fetchone()
        if row:
            marca = dict(row._mapping)
            marca["ativo"] = bool(marca.get("ativo"))

    marcas = _fetch_marcas()
    return render_template(
        "admin/cracha/produtos_marca.html",
        marcas=marcas,
        marca=marca,
        form_action=url_for("cracha_bp.produtos_marca"),
    )


@cracha_bp.route("/produtos/marca/<int:marca_id>/excluir", methods=["POST"])
@login_required
def produtos_marca_excluir(marca_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_pro_produtos_marca WHERE id_pk = :id"),
            {"id": marca_id},
        )
        db.session.commit()
        flash("Marca removida.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir marca")
        flash("Erro ao excluir marca.", "danger")
    return redirect(url_for("cracha_bp.produtos_marca"))


# ==============================================================================
# PEDIDOS DE CRACHÁ
# ==============================================================================

@cracha_bp.route("/pedidos")
@login_required
def pedidos():
    pesquisa = (request.args.get("pesquisa") or "").strip()
    filtro_etapa = (request.args.get("filtro_etapa") or "").strip()
    page = _safe_int(request.args.get("page"), 1)
    if page < 1:
        page = 1
    per_page = 15
    offset = (page - 1) * per_page

    where = ["etapa != 'finalizado'"]
    params = {}
    if pesquisa:
        where.append("empresa LIKE :pesquisa")
        params["pesquisa"] = f"%{pesquisa}%"
    if filtro_etapa and filtro_etapa != "finalizado":
        where.append("etapa = :etapa")
        params["etapa"] = filtro_etapa

    where_sql = " AND ".join(where)

    total = 0
    items = []
    try:
        total = db.session.execute(
            text(f"SELECT COUNT(*) AS total FROM pedidos_cracha WHERE {where_sql}"),
            params
        ).scalar() or 0
        
        rows = db.session.execute(
            text(
                "SELECT id, empresa, data_solicitacao, etapa, observacoes, data_criacao, criado_por, quantidade, tipo "
                f"FROM pedidos_cracha WHERE {where_sql} "
                "ORDER BY data_solicitacao DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": per_page, "offset": offset}
        ).fetchall()
        
        for row in rows:
            data = dict(row._mapping)
            if data.get("data_solicitacao"):
                ds = data["data_solicitacao"]
                if isinstance(ds, str):
                    try:
                        ds_dt = datetime.strptime(ds[:10], "%Y-%m-%d")
                        data["data_solicitacao_br"] = ds_dt.strftime("%d/%m/%Y")
                        data["data_solicitacao_iso"] = ds[:10]
                    except Exception:
                        data["data_solicitacao_br"] = ds
                        data["data_solicitacao_iso"] = ds
                else:
                    data["data_solicitacao_br"] = ds.strftime("%d/%m/%Y")
                    data["data_solicitacao_iso"] = ds.strftime("%Y-%m-%d")
            else:
                data["data_solicitacao_br"] = ""
                data["data_solicitacao_iso"] = ""
            items.append(data)
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao carregar pedidos de crachá")

    total_pages = max(1, math.ceil(total / per_page)) if total else 1

    clientes = []
    try:
        c_rows = db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes WHERE ativo = 1 ORDER BY nome_fantasia ASC")
        ).fetchall()
        clientes = [dict(r._mapping) for r in c_rows]
    except SQLAlchemyError:
        pass

    filtros = {
        "pesquisa": pesquisa,
        "filtro_etapa": filtro_etapa,
    }

    # Hide "finalizado" from active view stages dropdown filter
    etapas_list = [
        {"value": "recebimento", "label": "Recebimento", "class": "bg-secondary"},
        {"value": "layout_aprovacao", "label": "Montagem de Layout e Aprovação", "class": "bg-info text-dark"},
        {"value": "confeccao_bravasoft", "label": "Confecção no Bravasoft", "class": "bg-primary"},
        {"value": "confeccao_manual", "label": "Confecção Manual", "class": "bg-warning text-dark"},
        {"value": "finalizado", "label": "Finalizado", "class": "bg-success"},
    ]

    can_modify = _is_admin_user() or bool(_dept_names() & ALLOWED_DEPTS)

    return render_template(
        "admin/cracha/pedidos.html",
        pedidos=items,
        page=page,
        total_pages=total_pages,
        total_items=total,
        filtros=filtros,
        clientes=clientes,
        etapas=etapas_list,
        build_url=_build_url,
        date=date,
        can_modify=can_modify,
        is_historico=False,
    )


@cracha_bp.route("/pedidos/historico")
@login_required
def pedidos_historico():
    pesquisa = (request.args.get("pesquisa") or "").strip()
    page = _safe_int(request.args.get("page"), 1)
    if page < 1:
        page = 1
    per_page = 15
    offset = (page - 1) * per_page

    where = ["etapa = 'finalizado'"]
    params = {}
    if pesquisa:
        where.append("empresa LIKE :pesquisa")
        params["pesquisa"] = f"%{pesquisa}%"

    where_sql = " AND ".join(where)

    total = 0
    items = []
    try:
        total = db.session.execute(
            text(f"SELECT COUNT(*) AS total FROM pedidos_cracha WHERE {where_sql}"),
            params
        ).scalar() or 0
        
        rows = db.session.execute(
            text(
                "SELECT id, empresa, data_solicitacao, etapa, observacoes, data_criacao, criado_por, quantidade, tipo "
                f"FROM pedidos_cracha WHERE {where_sql} "
                "ORDER BY data_solicitacao DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": per_page, "offset": offset}
        ).fetchall()
        
        for row in rows:
            data = dict(row._mapping)
            if data.get("data_solicitacao"):
                data["data_solicitacao_br"] = data["data_solicitacao"].strftime("%d/%m/%Y")
                data["data_solicitacao_iso"] = data["data_solicitacao"].strftime("%Y-%m-%d")
            else:
                data["data_solicitacao_br"] = ""
                data["data_solicitacao_iso"] = ""
            items.append(data)
    except SQLAlchemyError:
        current_app.logger.exception("Falha ao carregar histórico de pedidos de crachá")

    total_pages = max(1, math.ceil(total / per_page)) if total else 1

    clientes = []
    try:
        c_rows = db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes WHERE ativo = 1 ORDER BY nome_fantasia ASC")
        ).fetchall()
        clientes = [dict(r._mapping) for r in c_rows]
    except SQLAlchemyError:
        pass

    filtros = {
        "pesquisa": pesquisa,
        "filtro_etapa": "finalizado",
    }

    etapas_list = [
        {"value": "recebimento", "label": "Recebimento", "class": "bg-secondary"},
        {"value": "layout_aprovacao", "label": "Montagem de Layout e Aprovação", "class": "bg-info text-dark"},
        {"value": "confeccao_bravasoft", "label": "Confecção no Bravasoft", "class": "bg-primary"},
        {"value": "confeccao_manual", "label": "Confecção Manual", "class": "bg-warning text-dark"},
        {"value": "finalizado", "label": "Finalizado", "class": "bg-success"},
    ]

    can_modify = _is_admin_user() or bool(_dept_names() & ALLOWED_DEPTS)

    return render_template(
        "admin/cracha/pedidos.html",
        pedidos=items,
        page=page,
        total_pages=total_pages,
        total_items=total,
        filtros=filtros,
        clientes=clientes,
        etapas=etapas_list,
        build_url=_build_url,
        date=date,
        can_modify=can_modify,
        is_historico=True,
    )


@cracha_bp.route("/pedidos/criar", methods=["POST"])
@login_required
def pedidos_criar():
    empresa = (request.form.get("empresa") or "").strip()
    data_solicitacao_str = (request.form.get("data_solicitacao") or "").strip()
    etapa = (request.form.get("etapa") or "recebimento").strip()
    observacoes = (request.form.get("observacoes") or "").strip()
    quantidade = _safe_int(request.form.get("quantidade"), 1)
    if quantidade < 1:
        quantidade = 1
    tipo = (request.form.get("tipo") or "cracha").strip()
    
    if not empresa or not data_solicitacao_str:
        flash("Empresa e data de solicitação são obrigatórias.", "danger")
        return redirect(url_for("cracha_bp.pedidos"))

    try:
        data_solicitacao = datetime.strptime(data_solicitacao_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Data de solicitação inválida.", "danger")
        return redirect(url_for("cracha_bp.pedidos"))

    try:
        db.session.execute(
            text(
                "INSERT INTO pedidos_cracha (empresa, data_solicitacao, etapa, observacoes, criado_por, quantidade, tipo) "
                "VALUES (:empresa, :data_solicitacao, :etapa, :observacoes, :criado_por, :quantidade, :tipo)"
            ),
            {
                "empresa": empresa,
                "data_solicitacao": data_solicitacao,
                "etapa": etapa,
                "observacoes": observacoes,
                "criado_por": getattr(current_user, "login", None) or "Sistema",
                "quantidade": quantidade,
                "tipo": tipo,
            }
        )
        db.session.commit()
        flash("Pedido de crachá cadastrado com sucesso.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao criar pedido de crachá")
        flash("Erro ao salvar o pedido.", "danger")
        
    return redirect(url_for("cracha_bp.pedidos"))


@cracha_bp.route("/pedidos/editar", methods=["POST"])
@login_required
def pedidos_editar():
    pedido_id = _safe_int(request.form.get("pedido_id"), None)
    empresa = (request.form.get("empresa") or "").strip()
    data_solicitacao_str = (request.form.get("data_solicitacao") or "").strip()
    etapa = (request.form.get("etapa") or "recebimento").strip()
    observacoes = (request.form.get("observacoes") or "").strip()
    quantidade = _safe_int(request.form.get("quantidade"), 1)
    if quantidade < 1:
        quantidade = 1
    tipo = (request.form.get("tipo") or "cracha").strip()
    
    if not pedido_id or not empresa or not data_solicitacao_str:
        flash("Dados insuficientes para edição.", "danger")
        return redirect(url_for("cracha_bp.pedidos"))

    try:
        data_solicitacao = datetime.strptime(data_solicitacao_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Data de solicitação inválida.", "danger")
        return redirect(url_for("cracha_bp.pedidos"))

    try:
        db.session.execute(
            text(
                "UPDATE pedidos_cracha SET empresa = :empresa, data_solicitacao = :data_solicitacao, "
                "etapa = :etapa, observacoes = :observacoes, quantidade = :quantidade, tipo = :tipo "
                "WHERE id = :id"
            ),
            {
                "id": pedido_id,
                "empresa": empresa,
                "data_solicitacao": data_solicitacao,
                "etapa": etapa,
                "observacoes": observacoes,
                "quantidade": quantidade,
                "tipo": tipo,
            }
        )
        db.session.commit()
        flash("Pedido de crachá atualizado com sucesso.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao editar pedido de crachá")
        flash("Erro ao atualizar o pedido.", "danger")
        
    return redirect(url_for("cracha_bp.pedidos"))


@cracha_bp.route("/pedidos/atualizar-etapa", methods=["POST"])
@login_required
def pedidos_atualizar_etapa():
    if _wants_json():
        data = request.get_json() or {}
        pedido_id = _safe_int(data.get("pedido_id"), None)
        etapa = (data.get("etapa") or "").strip()
    else:
        pedido_id = _safe_int(request.form.get("pedido_id"), None)
        etapa = (request.form.get("etapa") or "").strip()

    if not pedido_id or not etapa:
        return jsonify({"success": False, "message": "Parâmetros inválidos."}), 400

    try:
        db.session.execute(
            text("UPDATE pedidos_cracha SET etapa = :etapa WHERE id = :id"),
            {"id": pedido_id, "etapa": etapa}
        )
        db.session.commit()
        return jsonify({"success": True, "message": "Etapa atualizada com sucesso."})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao atualizar etapa do pedido de crachá")
        return jsonify({"success": False, "message": "Erro ao atualizar no banco de dados."}), 500


@cracha_bp.route("/pedidos/excluir/<int:pedido_id>", methods=["POST"])
@login_required
def pedidos_excluir(pedido_id: int):
    try:
        db.session.execute(
            text("DELETE FROM pedidos_cracha WHERE id = :id"),
            {"id": pedido_id}
        )
        db.session.commit()
        flash("Pedido excluído com sucesso.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir pedido de crachá")
        flash("Erro ao excluir o pedido.", "danger")
        
    return redirect(url_for("cracha_bp.pedidos"))

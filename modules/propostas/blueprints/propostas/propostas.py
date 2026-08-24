# blueprints/propostas/propostas.py

# ===========================================================
#  IMPORTS E CONFIGURAÇÃO GERAL
# ===========================================================

from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import json
import mimetypes
import os
import re
import unicodedata
import uuid
from PIL import Image
from typing import Any, Dict, Optional, Sequence
from types import SimpleNamespace
from sqlalchemy import or_

from flask import (
    current_app, render_template, redirect, url_for, flash, get_flashed_messages,
    request, session, jsonify, send_file, abort
)
from flask_login import current_user
from werkzeug.utils import secure_filename

from . import propostas_bp
from ..auth import login_required
from ..auth.permissions_utils import (
    current_permissions,
    normalize_role_key,
    raw_permissions,
)
from ...utils.item_rules import is_one_time_acquisition_item
from extensions import db

try:
    from modules.audit.utils import write_audit as _write_audit
except Exception:  # pragma: no cover - auditoria pode não estar disponível
    _write_audit = None

from utils.helpers import (
    wants_json as _wants_json,
    normalize_dept_name as _normalize_dept_name,
)







def _is_one_time_equipment(eq: Any) -> bool:
    return is_one_time_acquisition_item(
        getattr(eq, "name", None),
    )


def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            normalized = _normalize_dept_name(name)
            if normalized:
                names.add(normalized)
    except Exception:
        return set()
    return names


@propostas_bp.before_request
def _check_propostas_permission():
    from flask import request
    if "/api/" in getattr(request, "path", ""):
        return
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("propostas_bp."):
        return
    if endpoint == "propostas_bp.sem_permissao":
        return
    if not current_user.is_authenticated:
        return
    current_permissions()
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
    if role_key in {"admin", "gestor", "consultor"}:
        return
    proposal_depts = {"COMERCIAL", "ASSISTENCIA TECNICA", "ESTOQUE", "OFICINA"}
    if _dept_names() & proposal_depts:
        return
    if current_permissions().get(
        "propostas",
        False,
    ):
        return
    if _wants_json():
        return jsonify({"ok": False, "message": "Você não tem permissão para acessar as propostas."}), 403
    flash(
        "Você não tem permissão para acessar as Propostas. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("propostas_bp.sem_permissao"))


@propostas_bp.route("/sem-permissao")
@login_required
def sem_permissao():
    return render_template("errors/403.html", area_label="as Propostas")


def _proposal_audit_payload(proposal):
    if not proposal:
        return None

    def _safe(attr):
        return getattr(proposal, attr, None)

    payload = {
        "id": _safe("id"),
        "filename": _safe("filename"),
        "company": _safe("company"),
        "cnpj": _safe("cnpj"),
        "client_name": _safe("client_name"),
        "email": _safe("email"),
        "telefone": _safe("telefone"),
        "observacao_comercial": _safe("observacao_comercial"),
        "ambiente_incluir": bool(_safe("ambiente_incluir")),
        "ambiente_fotos": _safe("ambiente_fotos"),
        "servico_type": getattr(getattr(proposal, "servico_type", None), "name", None),
        "modalidade_type": getattr(getattr(proposal, "modalidade_type", None), "name", None),
        "issuer_company_code": _safe("issuer_company_code"),
        "pagamento": _safe("pagamento"),
        "prazo_entrega": _safe("prazo_entrega"),
        "frete": _safe("frete"),
        "validade": _safe("validade"),
        "garantia": _safe("garantia"),
        "garantia_sistema": _safe("garantia_sistema"),
        "enviar_email": bool(_safe("enviar_email")),
        "email_cc": _safe("email_cc"),
        "rep_categoria_programa": bool(_safe("rep_categoria_programa")),
        "rep_tem_mobile": bool(_safe("rep_tem_mobile")),
        "rep_qtd_mobile": _safe("rep_qtd_mobile"),
        "rep_mobile_valor_mensal": _safe("rep_mobile_valor_mensal"),
        "version_number": _safe("version_number"),
        "original_proposal_id": _safe("original_proposal_id"),
        "is_current": _safe("is_current"),
        "approved_at": _safe("approved_at"),
        "approved_by_id": _safe("approved_by_id"),
        "usuario_id": _safe("usuario_id"),
    }

    if getattr(proposal, "sistema_ativo", False):
        payload["sistema"] = {
            "nome": _safe("sistema_nome"),
            "descricao": _safe("sistema_descricao"),
            "imagem": _safe("sistema_imagem"),
            "quantidade": _safe("sistema_quantidade"),
            "preco_unitario": _safe("sistema_preco_unitario"),
            "preco_total": _safe("sistema_preco_total"),
        }

    equip_payload = []
    rel = getattr(proposal, "equipamentos", None)
    if rel is not None:
        try:
            iterator = rel.all()
        except Exception:
            iterator = rel
        for eq in iterator or []:
            equip_payload.append(
                {
                    "id": getattr(eq, "id", None),
                    "name": getattr(eq, "name", None),
                    "description": getattr(eq, "description", None),
                }
            )
    payload["equipamentos"] = equip_payload
    return payload


def _log_proposal_audit(proposal, *, action, message=None, before=None, include_after=True):
    if not _write_audit or proposal is None:
        return
    proposal_id = getattr(proposal, "id", None)
    if proposal_id is None:
        return
    after_payload = None
    if include_after:
        after_payload = _proposal_audit_payload(proposal)
    try:
        _write_audit(
            entity_type="Proposal",
            entity_id=proposal_id,
            action=action,
            message=message,
            before=before,
            after=after_payload,
            commit=True,
        )
    except Exception as exc:  # pragma: no cover - falha não deve quebrar fluxo
        try:
            current_app.logger.exception("Falha ao registrar auditoria da proposta %s: %s", proposal_id, exc)
        except Exception:
            pass


from ...models import (
    Equipment, Proposal, User,
    ParamOption, ParamCategory,
    ServicoType, ModalidadeType,
)
from ...forms import ProposalForm, cnpj_valido, cpf_valido
from ...services.pdf_jobs import manager as pdf_job_manager
from ...services.proposal_email import send_proposal_email
from ...constants import (
    ISSUER_COMPANIES,
    ISSUER_COMPANY_CHOICES,
    ISSUER_COMPANY_MAP,
    DEFAULT_ISSUER_CODE,
    DEFAULT_ISSUER_PHONE,
)
from ...gerar_proposta import (_build_html_context, _clean_phone, _format_phone, render_proposta_html_pdf)
from ...utils.timezone import get_local_timezone
from ...utils.systems import (
    SystemOption,
    iter_system_options,
    get_system_option,
    build_system_item,
    serialize_system_payload,
    parse_unit_price,
)
import dns.resolver


def _system_options_payload() -> list[dict]:
    return [opt.to_dict() for opt in iter_system_options()]


def _issuer_options_payload() -> list[dict]:
    payload: list[dict] = []
    for item in ISSUER_COMPANIES:
        phones = item.get("phones") or []
        if isinstance(phones, str):
            phones = [phones]
        phones = [p for p in phones if p]
        formatted_phones = [_format_phone(p) for p in phones] if phones else []
        phone_display = " | ".join(formatted_phones) if formatted_phones else ""
        address = item.get("address", "")
        site = item.get("site", "")
        footer_lines = []
        if address:
            footer_lines.append(address)
        if phone_display:
            footer_lines.append(phone_display)
        if site:
            footer_lines.append(site)
        payload.append({
            "code": item.get("code"),
            "name": item.get("name"),
            "address": address,
            "phones": formatted_phones,
            "phone_display": phone_display,
            "site": site,
            "email": item.get("email", ""),
            "cnpj": item.get("cnpj", ""),
            "footer_lines": footer_lines,
        })
    return payload


SIGNATURE_SUBDIR = "signatures"
AMBIENTE_SUBDIR = "uploads/propostas_ambiente"


def _signature_storage_dir() -> str:
    base = current_app.static_folder
    return os.path.join(base, SIGNATURE_SUBDIR)


def _ambiente_storage_dir() -> str:
    base = current_app.static_folder
    return os.path.join(base, AMBIENTE_SUBDIR)


def _save_signature_image(file_storage, user: "User") -> str:
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ValueError("Nenhuma assinatura enviada.")
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Nome de arquivo inválido.")
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Formato de assinatura inválido. Use PNG ou JPG.")
    storage_dir = _signature_storage_dir()
    os.makedirs(storage_dir, exist_ok=True)
    new_name = f"user_{user.id}.png"
    abs_path = os.path.join(storage_dir, new_name)
    file_storage.stream.seek(0)
    with Image.open(file_storage.stream) as img:
        img = img.convert('RGBA')
        img.thumbnail((800, 240), Image.LANCZOS)
        img.save(abs_path, format='PNG', optimize=True)
    return f"{SIGNATURE_SUBDIR}/{new_name}"


def _remove_signature_file(rel_path: str | None) -> None:
    if not rel_path:
        return
    abs_path = os.path.join(current_app.static_folder, rel_path)
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


LOCAL_TZ = get_local_timezone()
VALIDADE_DIAS = 15


# ===========================================================
#  HELPERS
# ===========================================================

def email_domain_has_mx(email: str) -> bool:
    try:
        domain = email.split("@")[-1]
        dns.resolver.resolve(domain, "MX")
        return True
    except Exception:
        return False


def _usuario_atual():
    try:
        if current_user.is_authenticated:
            return current_user
    except Exception:
        pass
    uid = session.get("usuario_id")
    if not uid:
        return None
    try:
        return User.query.get(int(uid))
    except (TypeError, ValueError):
        return User.query.get(uid)
    return User.query.get(uid) if uid else None


def _calcular_validade(data_base: datetime | None) -> str:
    base = data_base or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    validade = base.astimezone(LOCAL_TZ) + timedelta(days=VALIDADE_DIAS)
    return validade.strftime("%d/%m/%Y")


def _format_validade_input(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return None


def _validade_to_iso(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    try:
        return datetime.strptime(cleaned, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _padronizar_validade(proposta: Proposal) -> str:
    validade_raw = _format_validade_input(getattr(proposta, "validade", None))
    if validade_raw:
        proposta.validade = validade_raw
        return validade_raw
    validade = _calcular_validade(getattr(proposta, "data_criacao", None))
    proposta.validade = validade
    return validade


def _proposal_code_from_filename(filename: str | None) -> str:
    if not filename:
        return ""
    parts = filename.strip().split()
    return parts[-1] if parts else ""


def _proposal_download_label(proposta: Proposal) -> str:
    code = _proposal_code_from_filename(getattr(proposta, "filename", None))
    if code:
        return f"PROPOSTA COMERCIAL {code}"
    filename = (getattr(proposta, "filename", None) or "").strip()
    return filename or "PROPOSTA COMERCIAL"


def _normalize_photo_list(raw: object) -> list[dict[str, str]]:
    if not raw:
        return []

    def _append_item(items: list[dict[str, str]], value: object) -> None:
        if not value:
            return
        if isinstance(value, dict):
            src = value.get("src") or value.get("url") or value.get("path")
            if not src:
                return
            title = value.get("title") or ""
            items.append({"src": str(src), "title": str(title) if title else ""})
            return
        items.append({"src": str(value), "title": ""})

    items: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            _append_item(items, item)
        return items
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            _append_item(items, raw)
            return items
        if isinstance(parsed, list):
            for item in parsed:
                _append_item(items, item)
            return items
        _append_item(items, parsed)
        return items
    return []


def _collect_ambiente_files() -> list:
    files = []
    for key in ("ambiente_fotos", "ambiente_fotos[]"):
        files.extend(request.files.getlist(key))
    return [f for f in files if f and getattr(f, "filename", "")]


def _collect_ambiente_titles() -> list[str]:
    return [str(title or "").strip() for title in request.form.getlist("ambiente_titulos")]


def _save_ambiente_images(
    files: Sequence,
    titles: Sequence[str] | None,
    proposal_id: int,
) -> list[dict[str, str]]:
    saved: list[dict[str, str]] = []
    if not files:
        return saved
    title_list = list(titles or [])
    title_index = 0
    storage_dir = _ambiente_storage_dir()
    os.makedirs(storage_dir, exist_ok=True)
    for file_storage in files:
        if not file_storage or not getattr(file_storage, "filename", ""):
            continue
        filename = secure_filename(file_storage.filename or "")
        if not filename:
            continue
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if ext not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Formato de imagem do ambiente inválido. Use PNG ou JPG.")
        new_name = f"proposta_{proposal_id}_{uuid.uuid4().hex}{ext}"
        abs_path = os.path.join(storage_dir, new_name)
        file_storage.stream.seek(0)
        try:
            with Image.open(file_storage.stream) as img:
                if ext in {".jpg", ".jpeg"}:
                    img = img.convert("RGB")
                else:
                    img = img.convert("RGBA")
                img.thumbnail((1600, 1200), Image.LANCZOS)
                if ext in {".jpg", ".jpeg"}:
                    img.save(abs_path, format="JPEG", quality=88, optimize=True)
                else:
                    img.save(abs_path, format="PNG", optimize=True)
        except Exception as exc:  # pragma: no cover - validação extra
            raise ValueError("Arquivo de imagem do ambiente inválido.") from exc
        title_value = ""
        if title_index < len(title_list):
            title_value = str(title_list[title_index] or "").strip()
        title_index += 1
        saved.append({"src": f"{AMBIENTE_SUBDIR}/{new_name}", "title": title_value})
    return saved


def _preparar_equipamentos_para_proposta():
    ids       = session.get("equipamentos_buffer", [])
    quantias  = session.get("quantidades_buffer", {})
    descontos = session.get("descontos_buffer", {})
    precos    = session.get("precos_buffer", {})
    aquisicoes = session.get("aquisicoes_buffer", {})
    descricoes = session.get("descricoes_buffer", {})

    lista = []
    for eid in ids:
        eq = Equipment.query.get(eid)
        if not eq:
            continue
        quantity = int(quantias.get(str(eid), 1))
        discount = float(descontos.get(str(eid), 0))
        unit_price = float(precos.get(str(eid), eq.unit_price or 0.0))
        is_acquisition = bool(aquisicoes.get(str(eid), False)) or _is_one_time_equipment(eq)
        description = descricoes.get(str(eid)) if descricoes else getattr(eq, 'description', '')
        item = SimpleNamespace(
            id=eq.id,
            name=getattr(eq, 'name', ''),
            description=description,
            illustration_path=getattr(eq, 'illustration_path', None),
            unit_price=unit_price,
        )
        item.quantity = quantity
        item.discount_percent = discount
        item.is_acquisition = is_acquisition
        lista.append(item)

    sistema_payload = session.get("sistema_buffer")
    if sistema_payload:
        option = get_system_option(sistema_payload.get("key"))
        if option:
            lista.append(
                build_system_item(
                    option,
                    quantity=sistema_payload.get("quantity"),
                    unit_price=sistema_payload.get("unit_price"),
                    total_price=sistema_payload.get("total"),
                )
            )
    return lista


def _normalize_equipamentos_payload(raw: object) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []

    def _to_int(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _to_float(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_bool(value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on", "yes"}
        return bool(value)

    payload: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            eq_id = item.get("id") or item.get("equipment_id")
            if not eq_id:
                continue
            payload.append({
                "equipment_id": eq_id,
                "quantity": _to_int(item.get("quantity"), 1),
                "discount_percent": _to_float(item.get("discount_percent"), 0.0),
                "unit_price": item.get("unit_price") or item.get("manual_price"),
                "is_acquisition": _to_bool(item.get("is_acquisition")),
                "description": item.get("description") or "",
                "include_in_total": _to_bool(item.get("include_in_total", True)) if item.get("include_in_total") is not None else True,
            })
        return payload
    if isinstance(raw, dict):
        for key, item in raw.items():
            if not isinstance(item, dict):
                continue
            payload.append({
                "equipment_id": key,
                "quantity": _to_int(item.get("quantity"), 1),
                "discount_percent": _to_float(item.get("discount_percent"), 0.0),
                "unit_price": item.get("unit_price") or item.get("manual_price"),
                "is_acquisition": _to_bool(item.get("is_acquisition")),
                "description": item.get("description") or "",
                "include_in_total": _to_bool(item.get("include_in_total", True)) if item.get("include_in_total") is not None else True,
            })
        return payload
    return []


def _extract_system_selection(form):
    if not hasattr(form, "usar_sistema") or not form.usar_sistema.data:
        return None, None

    key = (form.sistema_opcao.data or "").strip()
    option = get_system_option(key)
    if not option:
        return None, None

    quantity = form.sistema_quantidade.data or option.default_quantity or 1
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = option.default_quantity or 1
    quantity = max(1, quantity)

    # Capturamos o preco bruto tanto do objeto 'form' quanto do 'request.form' diretamente
    # para evitar problemas com campos mascarados ou latencia de validacao.
    unit_raw = (request.form.get("sistema_preco_unitario") or form.sistema_preco_unitario.data or "").strip()
    unit_price = parse_unit_price(unit_raw)
    
    # Se o usuario nao digitou nada, ou digitou 0, tentamos buscar o default da opcao
    if unit_price <= 0 and not unit_raw:
        unit_price = option.unit_price or 0.0
    
    unit_price = max(0.0, float(unit_price))

    is_fixo = bool(getattr(form, "sistema_preco_manual", None) and form.sistema_preco_manual.data)
    payload = serialize_system_payload(option, quantity, unit_price, is_fixo=is_fixo)
    
    total = unit_price if is_fixo else (unit_price * quantity)
    payload["total"] = round(total, 2)
    return payload, option


def _system_item_from_proposal(prop: Proposal):
    if not getattr(prop, "sistema_ativo", False):
        return None

    option_label = prop.sistema_nome or "Sistema"
    option_desc = prop.sistema_descricao or ""
    
    # Se for um sistema do catálogo, mas tivermos descrição customizada persistida,
    # queremos garantir que o SimpleNamespace (item) a utilize.
    
    option = SystemOption(
        key=f"custom:{prop.id}",
        label=option_label,
        description=option_desc,
        image=prop.sistema_imagem or "",
        default_quantity=prop.sistema_quantidade or 1,
        unit_price=prop.sistema_preco_unitario or 0.0,
    )
    return build_system_item(
        option,
        quantity=prop.sistema_quantidade,
        unit_price=prop.sistema_preco_unitario,
        total_price=prop.sistema_preco_total,
        is_fixo=getattr(prop, "sistema_preco_fixo", False),
        description=option_desc,
    )

def _collect_proposal_items(prop: Proposal):
    payload = _normalize_equipamentos_payload(getattr(prop, "equipamentos_payload", None))
    eqs = []
    
    eq_lookup = {eq.id: eq for eq in prop.equipamentos.all()}
    
    for details in payload:
        eq_id = details.get("equipment_id")
        try:
            eq_id = int(eq_id)
        except (TypeError, ValueError):
            continue
            
        eq = eq_lookup.get(eq_id)
        if not eq:
            continue
            
        unit_price_val = details.get("unit_price")
        unit_price = 0.0
        if unit_price_val is not None:
            try:
                # Se for string vinda do form JS formatada:
                if isinstance(unit_price_val, str):
                    unit_price = parse_unit_price(unit_price_val)
                else:
                    unit_price = float(unit_price_val)
            except (TypeError, ValueError):
                unit_price = 0.0
        
        if unit_price <= 0:
            unit_price = float(getattr(eq, "unit_price", 0) or 0.0)

        item = SimpleNamespace(
            id=eq.id,
            name=getattr(eq, "name", ""),
            description=details.get("description") or getattr(eq, "description", ""),
            illustration_path=getattr(eq, "illustration_path", None),
            unit_price=unit_price,
            discount_percent=details.get("discount_percent", 0.0),
            quantity=details.get("quantity", 1),
            is_acquisition=bool(details.get("is_acquisition", False)) or _is_one_time_equipment(eq),
            include_in_total=bool(details.get("include_in_total", True)),
        )
        eqs.append(item)

    sistema_item = _system_item_from_proposal(prop)
    if sistema_item:
        eqs.append(sistema_item)
    return eqs


DEFAULT_COLAB_PHONE = DEFAULT_ISSUER_PHONE
DEFAULT_PROPOSTA_TEMPLATE = 'propostas/design_variants/circuit.html'


def _extrair_ddd(valor: str | None) -> str:
    """Retorna o DDD (2 dígitos) de um telefone, se existir."""
    digits = _clean_phone(valor or "")
    if len(digits) >= 10:
        return digits[-10:-8]
    return ""


def _telefones_por_filial(user: User, issuer_code: str) -> list[str]:
    """Prioriza telefones do usuário que combinam com o DDD da filial."""
    user_phones = user.all_contact_phones() or []
    issuer = ISSUER_COMPANY_MAP.get(issuer_code) or ISSUER_COMPANY_MAP.get(DEFAULT_ISSUER_CODE, {})
    ddds_filial = {
        _extrair_ddd(phone)
        for phone in ((issuer.get("phones") or []) + ([issuer.get("phone")] if issuer.get("phone") else []))
        if _extrair_ddd(phone)
    }
    if ddds_filial:
        compat = [p for p in user_phones if _extrair_ddd(p) in ddds_filial]
        if compat:
            return compat
    return user_phones or [DEFAULT_COLAB_PHONE]


def _dados_colaborador(proposta: Proposal | None = None):
    prop = proposta
    if prop is None:
        pid = session.get("ultima_proposta_id")
        prop = Proposal.query.get(pid) if pid else None

    if not prop:
        return "", "", [DEFAULT_COLAB_PHONE]

    usr = User.query.get(prop.usuario_id)
    if not usr:
        return "", "", [DEFAULT_COLAB_PHONE]

    issuer_code = prop.issuer_company_code or DEFAULT_ISSUER_CODE
    phones = _telefones_por_filial(usr, issuer_code)
    return usr.nome_completo or "", usr.email or "", phones


def _limpar_buffers_proposta():
    for chave in (
        "ultima_proposta_id",
        "equipamentos_buffer",
        "quantidades_buffer",
        "descontos_buffer",
        "precos_buffer",
        "sistema_buffer",
    ):
        session.pop(chave, None)


def _fill_selects(form: ProposalForm):
    def opts(cat):
        res = [("", "-- Selecione --")]
        res += [(o.label, o.label) for o in
                ParamOption.query.filter_by(category=cat)
                                 .order_by(ParamOption.label)]
        res.append(("outros", "Outros"))
        return res

    form.pagto_equip.choices   = opts(ParamCategory.PAGTO_EQUIP)
    form.prazo_entrega.choices = opts(ParamCategory.PRAZO_ENTREGA)
    form.frete.choices         = opts(ParamCategory.FRETE)
    form.garantia_eq.choices   = opts(ParamCategory.GARANTIA_EQ)
    form.garantia_sys.choices  = opts(ParamCategory.GARANTIA_SYS)


def _montar_contexto_pdf(proposta, equipamentos):
    _padronizar_validade(proposta)
    nome_colab, email_colab, phone_colab = _dados_colaborador(proposta)
    cod = proposta.filename.split()[-1] if proposta.filename else ''
    tel_raw = getattr(proposta, 'telefone', '') or ''
    return _build_html_context(
        proposta,
        equipamentos,
        nome_colaborador=nome_colab,
        email_colaborador=email_colab,
        proposta_cod=cod,
        tel_raw=tel_raw,
        tel_clean=_clean_phone(tel_raw),
        telefone_colaborador=phone_colab,
    )


def _gerar_pdf_stream(proposta, equipamentos, *, context=None, template_relpath=None, pdf_bytes=None):
    if pdf_bytes is None:
        if context is None:
            context = _montar_contexto_pdf(proposta, equipamentos)
        if template_relpath is None:
            template_relpath = current_app.config.get(
                "PROPOSTA_HTML_TEMPLATE",
                DEFAULT_PROPOSTA_TEMPLATE,
            )
        pdf_bytes = render_proposta_html_pdf(template_relpath, context)
    return io.BytesIO(pdf_bytes)


def _gerar_e_enviar_pdf(proposta, equipamentos, *, context=None, template_relpath=None, pdf_bytes=None, as_attachment=False):
    output = _gerar_pdf_stream(
        proposta,
        equipamentos,
        context=context,
        template_relpath=template_relpath,
        pdf_bytes=pdf_bytes,
    )
    return send_file(
        output,
        download_name=f"{_proposal_download_label(proposta)}.pdf",
        as_attachment=as_attachment,
    )


EMAIL_SPLIT_RE = re.compile(r"[;,\n]+")


def _parse_emails_list(raw: str) -> list[str]:
    if not raw:
        return []
    emails: list[str] = []
    for chunk in EMAIL_SPLIT_RE.split(raw):
        addr = chunk.strip()
        if not addr:
            continue
        if "@" not in addr or addr.startswith("@") or addr.endswith("@"):
            raise ValueError(f"E-mail inválido: {addr}")
        local, _, domain = addr.partition("@")
        if not local or "." not in domain:
            raise ValueError(f"E-mail inválido: {addr}")
        emails.append(addr)
    return emails


# ===========================================================
#  NOVA PROPOSTA
# ===========================================================

@propostas_bp.route("/nova_proposta", methods=["GET", "POST"])
@login_required
def nova_proposta():                    #  NENHUM espaço antes desta linha
    form = ProposalForm()
    _fill_selects(form)

    equipamentos_disp = Equipment.query.order_by(Equipment.name).all()
    form.equipments.choices = [(e.id, e.name) for e in equipamentos_disp]
    form.sistema_opcao.choices = [("", "-- Selecione --")] + [
        (opt.key, opt.label) for opt in iter_system_options()
    ]

    usuario_logado = _usuario_atual()
    signature_url = None
    if usuario_logado and getattr(usuario_logado, 'signature_path', None):
        signature_url = url_for('static', filename=usuario_logado.signature_path)

    outros = (User.query
              .filter(User.id != usuario_logado.id, User.tipo.in_(['consultor', 'gestor']))
              .order_by(User.nome_completo).all())

    form.outro_usuario.choices = [(u.id, u.nome_completo) for u in outros]

    if not form.issuer_company_code.data:
        form.issuer_company_code.data = DEFAULT_ISSUER_CODE

    # ------------------------------------------------------------------
    #  POST
    # ------------------------------------------------------------------
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def render_form(message: str | None = None, status: int = 400, category: str = 'danger', field_errors: dict | None = None):
        validade_default = _validade_to_iso(_calcular_validade(datetime.now(timezone.utc)))
        context = dict(
            form=form,
            equipments=equipamentos_disp,
            form_data=request.form,
            system_options=_system_options_payload(),
            issuer_options=_issuer_options_payload(),
            signature_url=signature_url,
            validade_default=validade_default,
        )

        if is_ajax:
            errors = field_errors or {k: v for k, v in form.errors.items() if v}
            if not message:
                flashed_messages = get_flashed_messages(with_categories=False)
                if flashed_messages:
                    message = flashed_messages[-1]
            payload = {"ok": False}
            if message:
                payload['message'] = message
            if errors:
                payload['errors'] = errors
            return jsonify(payload), status

        if message:
            flash(message, category)
        return render_template("nova_proposta.html", **context)

    if form.validate_on_submit():
        doc_type = (form.document_type.data or "cnpj").lower()
        raw_document = (form.document.data or "").strip()
        document_digits = "".join(filter(str.isdigit, raw_document))

        if document_digits:
            if doc_type == "cnpj":
                if len(document_digits) != 14 or not cnpj_valido(document_digits):
                    flash("CNPJ inválido.", "danger")
                    return render_form()
            else:
                if len(document_digits) != 11 or not cpf_valido(document_digits):
                    flash("CPF inválido.", "danger")
                    return render_form()

        company_value = (form.company.data or "").strip()
        # if doc_type == "cnpj" and not company_value:
            # flash("Informe a razão social/empresa para CNPJ.", "danger")
            # return render_form()
        if doc_type != "cnpj":
            company_value = company_value or "Empresa Teste"

        # Se CNPJ vazio, usar valor padrao
        if not company_value:
            company_value = "Empresa Teste"
        issuer_code = form.issuer_company_code.data or DEFAULT_ISSUER_CODE

        if issuer_code not in ISSUER_COMPANY_MAP:
            issuer_code = DEFAULT_ISSUER_CODE

        signature_file = request.files.get("signature_image")
        if usuario_logado and signature_file and getattr(signature_file, "filename", ""):
            try:
                new_signature_path = _save_signature_image(signature_file, usuario_logado)
            except ValueError as exc:
                flash(str(exc), "danger")
                return render_form()
            else:
                if usuario_logado.signature_path and usuario_logado.signature_path != new_signature_path:
                    _remove_signature_file(usuario_logado.signature_path)
                usuario_logado.signature_path = new_signature_path
                db.session.commit()
                signature_url = url_for('static', filename=new_signature_path)

        email = (form.email.data or "").strip()
        if email and not email_domain_has_mx(email):
            flash("Domínio de e-mail sem registro MX.", "danger")
            return render_form()

        enviar_email = form.enviar_email.data
        corpo_email = (form.email_corpo.data or "").strip()
        enviar_copia = form.enviar_copia.data
        cc_raw = (form.email_cc.data or "").strip() if enviar_copia else ""

        if enviar_email and not corpo_email:
            flash("Informe o conteúdo do e-mail para enviá-lo ao cliente.", "danger")
            return render_template(
                "nova_proposta.html",
                form=form,
                equipments=equipamentos_disp,
                form_data=request.form,
                system_options=_system_options_payload(),
                issuer_options=_issuer_options_payload(),
                signature_url=signature_url,
            )

        try:
            cc_list = _parse_emails_list(cc_raw) if enviar_email else []
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template(
                "nova_proposta.html",
                form=form,
                equipments=equipamentos_disp,
                form_data=request.form,
                system_options=_system_options_payload(),
                issuer_options=_issuer_options_payload(),
                signature_url=signature_url,
            )

        sistema_payload, sistema_option = _extract_system_selection(form)
        if form.usar_sistema.data and not sistema_option:
            flash("Selecione um Sistema de Ponto válido.", "danger")
            return render_template(
                "nova_proposta.html",
                form=form,
                equipments=equipamentos_disp,
                form_data=request.form,
                system_options=_system_options_payload(),
                issuer_options=_issuer_options_payload(),
                signature_url=signature_url,
            )

        user = usuario_logado
        if form.usar_outro_usuario.data == "sim":
            user = User.query.get(form.outro_usuario.data) or user

        nomes = user.nome_completo.strip().split()
        iniciais = (nomes[0][0] + (nomes[-1][0] if len(nomes) > 1 else "")).upper()
        if not iniciais:
            iniciais = user.usuario[:2].upper()

        numero = user.prox_num or 1
        user.prox_num = numero + 1
        db.session.commit()
        filename = f"PROPOSTA COMERCIAL {iniciais}{numero:02d}"
        created_at = datetime.now(timezone.utc)
        validade_auto = _calcular_validade(created_at)
        validade_input = _format_validade_input(form.validade.data)
        validade_final = validade_input or validade_auto

        sel = lambda campo, outro: outro.data.strip() if campo.data == "outros" else campo.data or ""
        servico_type_value = form.servico_type.data or ServicoType.PONTO
        modalidade_value = form.modalidade_type.data or ModalidadeType.AQUISICAO
        if modalidade_value == ModalidadeType.LOCACAO:
            locacao_vigencia = (form.locacao_vigencia.data or "").strip() or None
            locacao_modelo = (form.locacao_modelo.data or "").strip().lower()
            if locacao_modelo not in {"sintetico", "analitico"}:
                locacao_modelo = "sintetico"
            locacao_qtd_cnpjs = form.locacao_qtd_cnpjs.data or None
            locacao_qtd_equipamentos = form.locacao_qtd_equipamentos.data or None
        else:
            locacao_vigencia = None
            locacao_modelo = None
            locacao_qtd_cnpjs = None
            locacao_qtd_equipamentos = None

        rep_categoria_programa = bool(form.rep_categoria_programa.data)
        if servico_type_value != ServicoType.PONTO:
            rep_categoria_programa = False
        rep_tem_mobile = bool(form.rep_tem_mobile.data) if rep_categoria_programa else False
        try:
            rep_qtd_mobile = int(form.rep_qtd_mobile.data) if form.rep_qtd_mobile.data else None
        except (TypeError, ValueError):
            rep_qtd_mobile = None
        rep_mobile_valor_mensal = (
            parse_unit_price(form.rep_mobile_valor_mensal.data or "")
            if rep_tem_mobile
            else None
        )
        if not rep_tem_mobile:
            rep_qtd_mobile = None
            rep_mobile_valor_mensal = None

        proposta = Proposal(
            company=company_value,
            cnpj=document_digits,
            client_name=form.client_name.data,
            email=email,
            telefone=form.telefone.data,
            observacao_comercial=(form.observacao_comercial.data or "").strip() or None,
            ambiente_incluir=bool(form.ambiente_incluir.data),
            client_document_type=doc_type,
            issuer_company_code=issuer_code,
            pagamento=sel(form.pagto_equip, form.pagto_equip_other),
            prazo_entrega=sel(form.prazo_entrega, form.prazo_entrega_other),
            frete=sel(form.frete, form.frete_other),
            validade=validade_final,
            garantia=sel(form.garantia_eq, form.garantia_eq_other),
            garantia_sistema=sel(form.garantia_sys, form.garantia_sys_other),
            servico_type=servico_type_value,
            modalidade_type=modalidade_value,
            locacao_valor_mensal=None,
            locacao_vigencia=locacao_vigencia,
            locacao_modelo=locacao_modelo,
            locacao_qtd_cnpjs=locacao_qtd_cnpjs,
            locacao_qtd_equipamentos=locacao_qtd_equipamentos,
            usuario_id=user.id,
            data_criacao=created_at,
            filename=filename,
            enviar_email=enviar_email,
            email_corpo=corpo_email if enviar_email else "",
            email_cc=cc_raw if enviar_email else "",
            sistema_ativo=bool(sistema_payload),
            sistema_nome=sistema_option.label if sistema_option else None,
            sistema_descricao=(request.form.get("sistema_descricao_custom") or sistema_option.description) if sistema_option else None,
            sistema_imagem=sistema_option.image if sistema_option else None,
            sistema_quantidade=sistema_payload["quantity"] if sistema_payload else None,
            sistema_preco_unitario=sistema_payload["unit_price"] if sistema_payload else None,
            sistema_preco_total=sistema_payload["total"] if sistema_payload else None,
            sistema_preco_fixo=sistema_payload.get("is_fixo", False) if sistema_payload else False,
            rep_categoria_programa=rep_categoria_programa,
            rep_tem_mobile=rep_tem_mobile,
            rep_qtd_mobile=rep_qtd_mobile,
            rep_mobile_valor_mensal=rep_mobile_valor_mensal,
        )
        db.session.add(proposta)
        db.session.flush()
        if not proposta.original_proposal_id:
            proposta.original_proposal_id = proposta.id
        if not proposta.version_number:
            proposta.version_number = 1
        if proposta.is_current is None:
            proposta.is_current = True
        if proposta.is_original is None:
            proposta.is_original = True

        if proposta.ambiente_incluir:
            try:
                ambiente_fotos = _save_ambiente_images(
                    _collect_ambiente_files(),
                    _collect_ambiente_titles(),
                    proposta.id,
                )
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return render_form()
            if ambiente_fotos:
                proposta.ambiente_fotos = ambiente_fotos

        eqs = []
        equipamentos_ids = []
        payload_items = []
        quantidades_buffer = []
        descontos = []
        precos = []
        aquisicoes = []
        descricoes_dict = {}

        for uid in request.form.getlist("item_uids"):
            eid_str = request.form.get(f"equip_id_{uid}")
            if not eid_str:
                continue
            eq = Equipment.query.get(int(eid_str))
            if not eq:
                continue
            quantity = int(request.form.get(f"quantity_{uid}", 1))
            pct = float(request.form.get(f"discount_{uid}", "0") or 0)
            ps = request.form.get(f"price_{uid}", "").strip()
            is_acquisition = (
                request.form.get(f"acquisition_{uid}") in {"1", "true", "on", "yes"}
            ) or _is_one_time_equipment(eq)
            unit_price = eq.unit_price or 0.0
            if ps:
                parsed_price = parse_unit_price(ps)
                unit_price = parsed_price if parsed_price > 0 else (eq.unit_price or 0.0)

            description = request.form.get(f"description_{uid}", "").strip()
            include_in_total = request.form.get(f"include_in_total_{uid}") in {"1", "true", "on", "yes"}

            payload_items.append({
                "equipment_id": eq.id,
                "quantity": quantity,
                "discount_percent": pct,
                "unit_price": unit_price,
                "is_acquisition": bool(is_acquisition),
                "description": description,
                "include_in_total": bool(include_in_total),
            })

            quantidades_buffer.append(quantity)
            descontos.append(pct)
            precos.append(unit_price)
            aquisicoes.append(bool(is_acquisition))
            descricoes_dict[str(eq.id)] = description

            item = SimpleNamespace(
                id=eq.id,
                name=getattr(eq, 'name', ''),
                description=description,
                illustration_path=getattr(eq, 'illustration_path', None),
                unit_price=unit_price,
                is_acquisition=bool(is_acquisition),
            )
            item.quantity = quantity
            item.discount_percent = pct
            eqs.append(item)
            if eq.id not in equipamentos_ids:
                equipamentos_ids.append(eq.id)
                proposta.equipamentos.append(eq)

        if sistema_payload and sistema_option:
            # Override com o texto da textarea editável
            custom_desc = request.form.get("sistema_descricao_custom")
            if custom_desc is not None:
                proposta.sistema_descricao = custom_desc
            eqs.append(
                build_system_item(
                    sistema_option,
                    quantity=sistema_payload["quantity"],
                    unit_price=sistema_payload["unit_price"],
                    total_price=sistema_payload.get("total", sistema_payload["unit_price"]),
                    is_fixo=sistema_payload.get("is_fixo", False),
                    description=proposta.sistema_descricao,
                )
            )

        proposta.equipamentos_payload = payload_items

        db.session.commit()

        session_buffers = {
            "ultima_proposta_id": proposta.id,
            "equipamentos_buffer": equipamentos_ids,
            "quantidades_buffer": quantidades_buffer,
            "descontos_buffer": descontos,
            "precos_buffer": precos,
            "aquisicoes_buffer": aquisicoes,
            "descricoes_buffer": descricoes_dict,
        }
        if sistema_payload:
            session_buffers["sistema_buffer"] = {
                "key": sistema_payload["key"],
                "quantity": sistema_payload["quantity"],
                "unit_price": sistema_payload["unit_price"],
                "total": sistema_payload.get("total"),
            }
        else:
            session.pop("sistema_buffer", None)
        session.update(session_buffers)

        _log_proposal_audit(
            proposta,
            action="create",
            message=f"Proposta criada ({filename})",
        )

        acao = request.form.get("acao")
        if acao in {"baixar", "visualizar"} or (acao == "enviar_email" and enviar_email):
            template_relpath = current_app.config.get("PROPOSTA_HTML_TEMPLATE", DEFAULT_PROPOSTA_TEMPLATE)
            if is_ajax:
                context = _montar_contexto_pdf(proposta, eqs)
                email_payload = None
                if acao == "enviar_email":
                    email_payload = {"body": corpo_email, "cc": cc_list}
                job_id = pdf_job_manager.submit(
                    owner_id=usuario_logado.id if usuario_logado else 0,
                    action=acao,
                    proposal_id=proposta.id,
                    download_name=f"{_proposal_download_label(proposta)}.pdf",
                    template_relpath=template_relpath,
                    context=context,
                    email_payload=email_payload,
                )
                payload = {
                    "ok": True,
                    "job_id": job_id,
                    "action": acao,
                    "download_name": f"{_proposal_download_label(proposta)}.pdf",
                }
                if acao == "enviar_email":
                    payload["message"] = "Proposta enviada por e-mail com sucesso."
                return jsonify(payload), 202

            if acao == "enviar_email":
                context = _montar_contexto_pdf(proposta, eqs)
                pdf_bytes = render_proposta_html_pdf(template_relpath, context)
                try:
                    send_proposal_email(proposta, corpo_email, cc_list, pdf_bytes=pdf_bytes)
                except Exception as exc:
                    current_app.logger.exception("Falha ao enviar e-mail da proposta")
                    message = f"Não foi possível enviar o e-mail: {exc}"
                    return render_form(message=message, status=500)
                _limpar_buffers_proposta()
                flash("Proposta enviada por e-mail com sucesso.", "success")
                return redirect(url_for("propostas_bp.nova_proposta"))

            if acao == "baixar":
                return redirect(url_for("propostas_bp.baixar_proposta"))
            return redirect(url_for("propostas_bp.visualizar_proposta"))

        if is_ajax:
            return jsonify({"ok": True, "action": "salvar", "message": "Proposta criada com sucesso."})
        flash("Proposta criada com sucesso.", "success")
        return redirect(url_for("propostas_bp.nova_proposta"))

    # ------------------------------------------------------------------
    #  GET
    # ------------------------------------------------------------------
    return render_template(
        "nova_proposta.html",
        form=form,
        equipments=equipamentos_disp,
        form_data=request.form,
        system_options=_system_options_payload(),
        issuer_options=_issuer_options_payload(),
        signature_url=signature_url,
        validade_default=_validade_to_iso(_calcular_validade(datetime.now(timezone.utc))),
    )


# ===========================================================
#  BAIXAR / VISUALIZAR
# ===========================================================

@propostas_bp.route("/baixar_proposta")
@login_required
def baixar_proposta():
    pid = session.get("ultima_proposta_id")
    if not pid:
        flash("Nenhuma proposta para baixar.", "warning")
        return redirect(url_for("propostas_bp.nova_proposta"))

    prop = Proposal.query.get_or_404(pid)
    # Usa os buffers (acabou de criar)  contém qty/discount/price temporários
    eqs = _preparar_equipamentos_para_proposta()
    resp = _gerar_e_enviar_pdf(prop, eqs)

    # Força download
    resp.headers["Content-Disposition"] = f'attachment; filename="{_proposal_download_label(prop)}.pdf"'

    # Limpa buffers
    _limpar_buffers_proposta()
    return resp


@propostas_bp.route("/visualizar_proposta")
@login_required
def visualizar_proposta():
    pid = session.get("ultima_proposta_id")
    if not pid:
        flash("Nenhuma proposta para visualizar.", "warning")
        return redirect(url_for("propostas_bp.nova_proposta"))

    prop = Proposal.query.get_or_404(pid)
    eqs = _preparar_equipamentos_para_proposta()
    resp = _gerar_e_enviar_pdf(prop, eqs)

    # Limpa buffers
    _limpar_buffers_proposta()
    return resp


# ===========================================================
#  DOWNLOAD / EDITAR / EXCLUIR / HISTÓRICO
# ===========================================================

@propostas_bp.route("/api/jobs/<job_id>", methods=["GET"])
@login_required
def job_status(job_id: str):
    pdf_job_manager.cleanup()

    user = _usuario_atual()
    owner_id = user.id if user else 0

    job = pdf_job_manager.get(job_id, owner_id)
    if not job:
        return jsonify({"ok": False, "message": "Tarefa não encontrada."}), 404

    def _format_size(value: Optional[int]) -> Optional[str]:
        if value is None:
            return None
        size = float(value)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024 or unit == 'TB':
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024
        return None

    data: Dict[str, Any] = {
        "ok": True,
        "job_id": job.id,
        "status": job.status,
        "action": job.action,
        "download_name": job.download_name,
        "generated_at": job.generated_at.isoformat() if job.generated_at else None,
    }

    if job.payload:
        data.update(job.payload)

    if job.status == 'done':
        if job.file_path:
            data["download_url"] = url_for("propostas_bp.job_download", job_id=job.id)
            data["inline_url"] = url_for("propostas_bp.job_download", job_id=job.id, disposition="inline")
        if job.file_size is not None:
            data["file_size"] = job.file_size
            readable = _format_size(job.file_size)
            if readable:
                data["file_size_readable"] = readable
        if job.action == 'enviar_email':
            _limpar_buffers_proposta()
    if job.status == 'error':
        data["message"] = job.error or 'Falha ao gerar a proposta.'

    return jsonify(data)


@propostas_bp.route("/api/jobs/<job_id>/download")
@login_required
def job_download(job_id: str):
    user = _usuario_atual()
    owner_id = user.id if user else 0

    job = pdf_job_manager.get(job_id, owner_id)

    if not job or job.status != 'done' or not job.file_path or job.action not in {'baixar', 'visualizar'}:
        abort(404)

    file_path = Path(job.file_path)
    if not file_path.exists():
        abort(404)

    disposition = request.args.get("disposition", "attachment")
    as_attachment = disposition != "inline"

    response = send_file(str(file_path), as_attachment=as_attachment, download_name=job.download_name)
    return response


@propostas_bp.route("/download_proposta/<int:id>")
@login_required
def download_proposta(id):
    prop = Proposal.query.get_or_404(id)
    before_snapshot = _proposal_audit_payload(prop) if request.method == 'POST' else None

    if session.get("tipo") not in ["admin", "gestor"] and prop.usuario_id != session.get("usuario_id"):
        flash("Sem permissão.", "danger")
        return redirect(url_for("propostas_bp.historico_propostas"))

    eqs = _collect_proposal_items(prop)
    return _gerar_e_enviar_pdf(prop, eqs)


@propostas_bp.route("/api/propostas/<int:proposal_id>/pdf", methods=["POST"])
@login_required
def api_proposta_pdf(proposal_id: int):
    prop = Proposal.query.get_or_404(proposal_id)

    user = _usuario_atual()
    owner_id = getattr(user, "id", None) or session.get("usuario_id") or 0
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        owner_id = 0
    user_role = (getattr(user, "tipo", None) or session.get("tipo") or "").lower()
    if user_role not in ("admin", "gestor") and prop.usuario_id != owner_id:
        return jsonify({"ok": False, "message": "Sem permissão."}), 403

    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "visualizar").strip().lower()
    if action not in {"visualizar", "baixar"}:
        action = "visualizar"

    eqs = _collect_proposal_items(prop)
    context = _montar_contexto_pdf(prop, eqs)
    template_relpath = current_app.config.get("PROPOSTA_HTML_TEMPLATE", DEFAULT_PROPOSTA_TEMPLATE)
    download_name = f"{_proposal_download_label(prop)}.pdf"

    try:
        job_id = pdf_job_manager.submit(
            owner_id=owner_id,
            action=action,
            proposal_id=prop.id,
            download_name=download_name,
            template_relpath=template_relpath,
            context=context,
        )
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Falha ao enfileirar PDF do histórico", exc_info=exc)
        return jsonify({"ok": False, "message": "Falha ao preparar o PDF."}), 500

    return jsonify({
        "ok": True,
        "action": action,
        "job_id": job_id,
        "download_name": download_name,
    })


@propostas_bp.route("/editar_proposta/<int:id>", methods=["GET", "POST"])
@login_required
def editar_proposta(id):
    prop = Proposal.query.get_or_404(id)

    if session.get("tipo") not in ["admin", "gestor"] and prop.usuario_id != session.get("usuario_id"):
        return jsonify({"error": "Acesso não autorizado."}), 403
    is_admin = session.get("tipo") == "admin"

    if not prop.original_proposal_id:
        prop.original_proposal_id = prop.id
    if not prop.version_number:
        prop.version_number = 1
    if prop.is_original is None:
        prop.is_original = prop.version_number == 1
    if prop.is_current is None:
        prop.is_current = True
    db.session.commit()

    if request.method == "POST":
        if prop.approved_at and not is_admin:
            return jsonify({"error": "Proposta aprovada não pode ser editada."}), 400
        if prop.is_current is False and not is_admin:
            return jsonify({"error": "Apenas a versão atual pode ser editada."}), 400
        before_snapshot = _proposal_audit_payload(prop)

        doc_type = (request.form.get("document_type") or "cnpj").lower()
        raw_document = (request.form.get("document") or "").strip()
        document_digits = "".join(filter(str.isdigit, raw_document))

        if doc_type == "cnpj":
            if document_digits and (len(document_digits) != 14 or not cnpj_valido(document_digits)):
                return jsonify({"error": "CNPJ inválido."}), 400
        else:
            if document_digits and (len(document_digits) != 11 or not cpf_valido(document_digits)):
                return jsonify({"error": "CPF inválido."}), 400

        company_value = (request.form.get("company") or "").strip()
        # if doc_type == "cnpj" and not company_value:
            # return jsonify({"error": "Informe a razão social/empresa para CNPJ."}), 400
        if doc_type != "cnpj":
            company_value = company_value or "Empresa Teste"

        cnpj_value = document_digits or prop.cnpj
        issuer_code_post = request.form.get("issuer_company_code") or DEFAULT_ISSUER_CODE
        if issuer_code_post not in ISSUER_COMPANY_MAP:
            issuer_code_post = DEFAULT_ISSUER_CODE

        servico_raw = request.form.get("servico_type")
        servico_type_value = ServicoType[servico_raw] if servico_raw else prop.servico_type
        modalidade_raw = request.form.get("modalidade_type")
        modalidade_value = ModalidadeType[modalidade_raw] if modalidade_raw else prop.modalidade_type

        enviar_email = request.form.get("enviar_email") in {"1", "true", "on", "yes"}
        email_corpo = (request.form.get("email_corpo") or "").strip()
        email_cc = (request.form.get("email_cc") or "").strip()

        client_name = request.form.get("client_name")
        email = request.form.get("email")
        telefone = request.form.get("telefone")
        observacao_comercial = (request.form.get("observacao_comercial") or "").strip() or None
        ambiente_incluir = request.form.get("ambiente_incluir") in {"1", "true", "on", "yes"}
        pagamento = request.form.get("pagamento")
        prazo_entrega = request.form.get("prazo_entrega")
        frete = request.form.get("frete")
        validade = request.form.get("validade")
        garantia = request.form.get("garantia")
        garantia_sistema = request.form.get("garantia_sistema")

        usar_outro_raw = (request.form.get("usar_outro_usuario") or "nao").strip().lower()
        if usar_outro_raw == "sim":
            outro_usuario = request.form.get("outro_usuario")
            try:
                outro_usuario_id = int(outro_usuario) if outro_usuario else None
            except (TypeError, ValueError):
                outro_usuario_id = None
            if not outro_usuario_id:
                return jsonify({"error": "Selecione o consultor responsável."}), 400
            outro_user = User.query.get(outro_usuario_id)
            if not outro_user:
                return jsonify({"error": "Consultor selecionado não encontrado."}), 400
            usuario_id = outro_user.id
        else:
            usuario_id = session.get("usuario_id") or prop.usuario_id

        usar_sistema = bool(request.form.get("usar_sistema"))
        is_fixo_sistema = request.form.get("sistema_preco_manual") in {"1", "true", "on", "yes"}
        if usar_sistema:
            sistema_key = (request.form.get("sistema_opcao") or "").strip()
            option = get_system_option(sistema_key)
            if not option:
                return jsonify({"error": "Selecione um sistema válido."}), 400
            try:
                quantidade = int(request.form.get("sistema_quantidade") or 1)
            except (TypeError, ValueError):
                quantidade = 1
            if quantidade < 1:
                quantidade = 1
            unit_price = parse_unit_price(request.form.get("sistema_preco_unitario") or "")
            total_price = unit_price if is_fixo_sistema else (quantidade * unit_price)
            sistema_ativo = True
            sistema_nome = option.label
            sistema_descricao = (request.form.get("sistema_descricao_custom") or option.description)
            sistema_imagem = option.image
            sistema_quantidade = quantidade
            sistema_preco_unitario = unit_price
            sistema_preco_total = total_price
        else:
            sistema_ativo = False
            sistema_nome = None
            sistema_descricao = None
            sistema_imagem = None
            sistema_quantidade = None
            sistema_preco_unitario = None
            sistema_preco_total = None

        if modalidade_value == ModalidadeType.LOCACAO:
            locacao_vigencia = (request.form.get("locacao_vigencia") or "").strip() or None
            locacao_modelo = (request.form.get("locacao_modelo") or "").strip().lower()
            if locacao_modelo not in {"sintetico", "analitico"}:
                locacao_modelo = "sintetico"
            try:
                locacao_qtd_cnpjs = int(request.form.get("locacao_qtd_cnpjs") or 0) or None
            except (TypeError, ValueError):
                locacao_qtd_cnpjs = None
            try:
                locacao_qtd_equipamentos = int(request.form.get("locacao_qtd_equipamentos") or 0) or None
            except (TypeError, ValueError):
                locacao_qtd_equipamentos = None
        else:
            locacao_vigencia = None
            locacao_modelo = None
            locacao_qtd_cnpjs = None
            locacao_qtd_equipamentos = None

        rep_categoria_programa = bool(request.form.get("rep_categoria_programa"))
        if servico_type_value and servico_type_value != ServicoType.PONTO:
            rep_categoria_programa = False
        rep_tem_mobile = bool(request.form.get("rep_tem_mobile")) if rep_categoria_programa else False
        try:
            rep_qtd_mobile = int(request.form.get("rep_qtd_mobile") or 0) or None
        except (TypeError, ValueError):
            rep_qtd_mobile = None
        rep_mobile_valor_mensal = (
            parse_unit_price(request.form.get("rep_mobile_valor_mensal") or "")
            if rep_tem_mobile
            else None
        )
        if not rep_tem_mobile:
            rep_qtd_mobile = None
            rep_mobile_valor_mensal = None

        original_id = prop.original_proposal_id or prop.id
        max_version = (
            db.session.query(db.func.max(Proposal.version_number))
            .filter(or_(Proposal.original_proposal_id == original_id, Proposal.id == original_id))
            .scalar()
        )
        next_version = (max_version or prop.version_number or 1) + 1
        created_at = datetime.now(timezone.utc)
        validade_auto = _calcular_validade(created_at)
        validade_input = _format_validade_input(validade)
        validade_final = validade_input or validade_auto

        (
            Proposal.query.filter(
                or_(
                    Proposal.original_proposal_id == original_id,
                    Proposal.id == original_id,
                )
            )
            .update({"is_current": False}, synchronize_session=False)
        )

        new_prop = Proposal(
            company=company_value,
            cnpj=cnpj_value,
            client_name=client_name,
            email=email,
            telefone=telefone,
            observacao_comercial=observacao_comercial,
            ambiente_incluir=ambiente_incluir,
            client_document_type=doc_type,
            issuer_company_code=issuer_code_post,
            pagamento=pagamento,
            prazo_entrega=prazo_entrega,
            frete=frete,
            validade=validade_final,
            garantia=garantia,
            garantia_sistema=garantia_sistema,
            servico_type=servico_type_value,
            modalidade_type=modalidade_value,
            locacao_valor_mensal=None,
            locacao_vigencia=locacao_vigencia,
            locacao_modelo=locacao_modelo,
            locacao_qtd_pessoas=None,
            locacao_qtd_cnpjs=locacao_qtd_cnpjs,
            locacao_qtd_equipamentos=locacao_qtd_equipamentos,
            usuario_id=usuario_id,
            data_criacao=created_at,
            filename=prop.filename,
            enviar_email=enviar_email,
            email_corpo=email_corpo if enviar_email else "",
            email_cc=email_cc if enviar_email else "",
            sistema_ativo=sistema_ativo,
            sistema_nome=sistema_nome,
            sistema_descricao=sistema_descricao,
            sistema_imagem=sistema_imagem,
            sistema_quantidade=sistema_quantidade,
            sistema_preco_unitario=sistema_preco_unitario,
            sistema_preco_total=sistema_preco_total,
            sistema_preco_fixo=is_fixo_sistema,
            rep_categoria_programa=rep_categoria_programa,
            rep_tem_mobile=rep_tem_mobile,
            rep_qtd_mobile=rep_qtd_mobile,
            rep_mobile_valor_mensal=rep_mobile_valor_mensal,
        )
        db.session.add(new_prop)
        db.session.flush()

        existing_photos = _normalize_photo_list(getattr(prop, "ambiente_fotos", None))
        new_photos: list[dict[str, str]] = []
        if ambiente_incluir:
            try:
                new_photos = _save_ambiente_images(
                    _collect_ambiente_files(),
                    _collect_ambiente_titles(),
                    new_prop.id,
                )
            except ValueError as exc:
                db.session.rollback()
                return jsonify({"error": str(exc)}), 400
        combined_photos: list[dict[str, str]] = []
        seen_photos = set()
        for item in existing_photos + new_photos:
            if not item:
                continue
            src = item.get("src") if isinstance(item, dict) else None
            if not src or src in seen_photos:
                continue
            seen_photos.add(src)
            combined_photos.append({"src": src, "title": item.get("title") or ""})
        if combined_photos:
            new_prop.ambiente_fotos = combined_photos

        new_prop.original_proposal_id = original_id
        new_prop.version_number = next_version
        new_prop.is_current = True
        new_prop.is_original = False
        prop.is_current = False

        payload_items = []
        equipamentos_ids = []
        for uid in request.form.getlist("item_uids"):
            eid_str = request.form.get(f"equip_id_{uid}")
            if not eid_str:
                continue
            eq = Equipment.query.get(int(eid_str))
            if not eq:
                continue
            quantity = int(request.form.get(f"quantity_{uid}", 1))
            pct = float(request.form.get(f"discount_{uid}", "0") or 0)
            ps = request.form.get(f"price_{uid}", "").strip()
            is_acquisition = (
                request.form.get(f"acquisition_{uid}") in {"1", "true", "on", "yes"}
            ) or _is_one_time_equipment(eq)
            unit_price = eq.unit_price or 0.0
            if ps:
                parsed_price = parse_unit_price(ps)
                unit_price = parsed_price if parsed_price > 0 else (eq.unit_price or 0.0)

            description = request.form.get(f"description_{uid}", "").strip()
            include_in_total = request.form.get(f"include_in_total_{uid}") in {"1", "true", "on", "yes"}

            payload_items.append({
                "equipment_id": eq.id,
                "quantity": quantity,
                "discount_percent": pct,
                "unit_price": unit_price,
                "is_acquisition": bool(is_acquisition),
                "description": description,
                "include_in_total": bool(include_in_total),
            })
            if eq.id not in equipamentos_ids:
                equipamentos_ids.append(eq.id)
                new_prop.equipamentos.append(eq)

        # Override de descrição
        if new_prop.sistema_ativo:
            custom_desc = request.form.get("sistema_descricao_custom")
            if custom_desc is not None:
                new_prop.sistema_descricao = custom_desc

        new_prop.equipamentos_payload = payload_items

        db.session.commit()

        _log_proposal_audit(
            new_prop,
            action="version",
            message=f"Nova versão criada ({new_prop.filename or new_prop.client_name})",
            before=before_snapshot,
        )

        return jsonify(
            {
                "success": True,
                "message": f"Proposta atualizada. Versão {next_version} criada.",
                "new_id": new_prop.id,
            }
        )

    # --- GET  retorna JSON ---
    equip_payload = _normalize_equipamentos_payload(getattr(prop, "equipamentos_payload", None))
    eq_list = []
    eq_lookup = {eq.id: eq for eq in prop.equipamentos.all()}
    
    for details in equip_payload:
        eq_id = details.get("equipment_id")
        try:
            eq_id = int(eq_id)
        except (TypeError, ValueError):
            continue
        eq = eq_lookup.get(eq_id)
        if not eq:
            continue
            
        quantity = details.get("quantity", 1)
        if quantity <= 0:
            quantity = getattr(eq, "quantity", 1) or 1
            
        discount = details.get("discount_percent", 0.0)
        
        unit_price = details.get("unit_price")
        if unit_price is None or unit_price <= 0:
            unit_price = getattr(eq, "unit_price", 0) or 0
            
        eq_list.append(
            {
                "id": eq.id,
                "name": eq.name,
                "quantity": quantity,
                "stock_quantity": int(getattr(eq, "quantity", 0) or 0),
                "discount_percent": discount,
                "unit_price": unit_price,
                "catalog_price": float(getattr(eq, "unit_price", 0) or 0.0),
                "is_acquisition": bool(details.get("is_acquisition", False)) or _is_one_time_equipment(eq),
                "description": details.get("description") or getattr(eq, "description", ""),
                "include_in_total": bool(details.get("include_in_total", True)),
            }
        )
    doc_type = prop.client_document_type or ("cnpj" if len((prop.cnpj or "")) == 14 else "cpf")

    current_user_id = session.get("usuario_id")
    owner_user_id = prop.usuario_id
    usar_outro_flag = "sim" if owner_user_id and owner_user_id != current_user_id else "nao"
    outro_usuario_id = owner_user_id if usar_outro_flag == "sim" else None

    sistema_key = None
    if prop.sistema_ativo and prop.sistema_nome:
        normalized_label = (prop.sistema_nome or "").strip().lower()
        for option in iter_system_options():
            if option.label.strip().lower() == normalized_label:
                sistema_key = option.key
                break

    return jsonify(
        proposta_id=prop.id,
        company=prop.company,
        document=prop.cnpj,
        document_type=doc_type,
        client_name=prop.client_name,
        email=prop.email,
        telefone=prop.telefone,
        observacao_comercial=prop.observacao_comercial,
        pagamento=prop.pagamento,
        prazo_entrega=prop.prazo_entrega,
        frete=prop.frete,
        validade=prop.validade,
        garantia=prop.garantia,
        garantia_sistema=prop.garantia_sistema,
        servico_type=prop.servico_type.name if prop.servico_type else "",
        modalidade_type=prop.modalidade_type.name if prop.modalidade_type else "",
        locacao_vigencia=prop.locacao_vigencia,
        locacao_modelo=prop.locacao_modelo,
        locacao_qtd_cnpjs=prop.locacao_qtd_cnpjs,
        locacao_qtd_equipamentos=prop.locacao_qtd_equipamentos,
        rep_categoria_programa=bool(prop.rep_categoria_programa),
        rep_tem_mobile=bool(getattr(prop, "rep_tem_mobile", False)),
        rep_qtd_mobile=getattr(prop, "rep_qtd_mobile", None),
        rep_mobile_valor_mensal=getattr(prop, "rep_mobile_valor_mensal", None),
        ambiente_incluir=bool(getattr(prop, "ambiente_incluir", False)),
        enviar_email=prop.enviar_email,
        email_corpo=prop.email_corpo,
        email_cc=prop.email_cc,
        owner_user_id=owner_user_id,
        current_user_id=current_user_id,
        usar_outro_usuario=usar_outro_flag,
        outro_usuario_id=outro_usuario_id,
        equipamentos=eq_list,
        sistema_ativo=bool(prop.sistema_ativo),
        sistema_key=sistema_key,
        sistema_nome=prop.sistema_nome,
        sistema_descricao=prop.sistema_descricao,
        sistema_imagem=prop.sistema_imagem,
        sistema_quantidade=prop.sistema_quantidade,
        sistema_preco_unitario=prop.sistema_preco_unitario,
        sistema_preco_total=prop.sistema_preco_total,
        sistema_preco_manual=bool(prop.sistema_preco_fixo),
        issuer_company_code=prop.issuer_company_code or DEFAULT_ISSUER_CODE,
        client_document_type=doc_type,
    )


@propostas_bp.route("/aprovar_proposta/<int:id>", methods=["POST"])
@login_required
def aprovar_proposta(id: int):
    prop = Proposal.query.get_or_404(id)

    user = _usuario_atual()
    user_id = getattr(user, "id", None) or session.get("usuario_id")
    try:
        user_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        user_id = None
    user_role = (getattr(user, "tipo", None) or session.get("tipo") or "").lower()

    if user_role not in ("admin", "gestor") and prop.usuario_id != user_id:
        return jsonify({"ok": False, "message": "Sem permissão para aprovar esta proposta."}), 403

    if prop.approved_at:
        return jsonify({"ok": True, "message": "Esta versao ja foi aprovada."})

    prop.approved_at = datetime.now(timezone.utc)
    prop.approved_by_id = user_id
    db.session.commit()

    _log_proposal_audit(
        prop,
        action="approve",
        message=f"Versao aprovada ({prop.filename or prop.client_name})",
    )

    return jsonify({"ok": True, "message": "Versao marcada como aprovada."})


@propostas_bp.route("/excluir_proposta/<int:id>", methods=["POST"])
@login_required
def excluir_proposta(id):
    if session.get("tipo") not in ["admin", "gestor"]:
        return jsonify({"error": "Acesso negado"}), 403

    prop = Proposal.query.get_or_404(id)
    before_snapshot = _proposal_audit_payload(prop)
    audit_stub = SimpleNamespace(id=prop.id, filename=getattr(prop, 'filename', None), client_name=getattr(prop, 'client_name', None))

    db.session.delete(prop)
    db.session.commit()

    _log_proposal_audit(
        audit_stub,
        action="delete",
        message=(f"Proposta excluída ({before_snapshot.get('filename') or before_snapshot.get('client_name')})" if before_snapshot else "Proposta excluída"),
        before=before_snapshot,
        include_after=False,
    )

    flash("Proposta excluída com sucesso.", "info")
    return redirect(url_for("propostas_bp.historico_propostas"))


@propostas_bp.route("/historico_propostas")
@login_required
def historico_propostas():
    tipo = session.get("tipo")
    data_filter = request.args.get("data")
    page = request.args.get("page", 1, type=int)
    company_filter = (request.args.get("empresa") or "").strip()
    serv_filter = request.args.get("servico_type")
    mod_filter = request.args.get("modalidade_type")
    user_filter = request.args.get("usuario_id", type=int)
    issuer_filter = (request.args.get("issuer_code") or "").strip()
    if issuer_filter and issuer_filter not in ISSUER_COMPANY_MAP:
        issuer_filter = ""

    q = Proposal.query
    if tipo not in ["admin", "gestor"]:
        q = q.filter_by(usuario_id=session.get("usuario_id"))
    q_options = q

    if data_filter:
        try:
            dia = datetime.strptime(data_filter, "%Y-%m-%d").date()
            q = q.filter(db.func.date(Proposal.data_criacao) == dia)
            q_options = q_options.filter(db.func.date(Proposal.data_criacao) == dia)
        except ValueError:
            flash("Data inválida.", "warning")

    if user_filter:
        q = q.filter_by(usuario_id=user_filter)
        q_options = q_options.filter_by(usuario_id=user_filter)
    if company_filter:
        company_digits = re.sub(r"\D", "", company_filter)
        company_like = f"%{company_filter.lower()}%"
        if company_digits:
            q = q.filter(
                or_(
                    db.func.lower(Proposal.company).like(company_like),
                    Proposal.cnpj.like(f"%{company_digits}%"),
                )
            )
        else:
            q = q.filter(db.func.lower(Proposal.company).like(company_like))
    if serv_filter:
        q = q.filter_by(servico_type=ServicoType[serv_filter])
        q_options = q_options.filter_by(servico_type=ServicoType[serv_filter])
    if mod_filter:
        q = q.filter_by(modalidade_type=ModalidadeType[mod_filter])
        q_options = q_options.filter_by(modalidade_type=ModalidadeType[mod_filter])
    if issuer_filter:
        q = q.filter(Proposal.issuer_company_code == issuer_filter)
        q_options = q_options.filter(Proposal.issuer_company_code == issuer_filter)

    empresa_rows = (
        q_options.with_entities(db.func.trim(Proposal.company).label("company"))
        .filter(Proposal.company.isnot(None))
        .filter(db.func.trim(Proposal.company) != "")
        .distinct()
        .order_by(db.func.lower(db.func.trim(Proposal.company)))
        .all()
    )
    empresa_options = [row.company for row in empresa_rows if row.company]

    q = q.filter(or_(Proposal.is_current.is_(True), Proposal.is_current.is_(None)))
    propostas = q.order_by(Proposal.data_criacao.desc()).paginate(page=page, per_page=10)

    # Ajuste de fuso horário
    seed_changed = False
    for p in propostas.items:
        if not p.original_proposal_id:
            p.original_proposal_id = p.id
            seed_changed = True
        if not p.version_number:
            p.version_number = 1
            seed_changed = True
        if p.is_current is None:
            p.is_current = True
            seed_changed = True
        if p.is_original is None:
            p.is_original = p.version_number == 1
            seed_changed = True
        if p.data_criacao:
            if p.data_criacao.tzinfo is None:
                p.data_criacao = p.data_criacao.replace(tzinfo=timezone.utc)
            p.data_criacao = p.data_criacao.astimezone(LOCAL_TZ)
            p.data_criacao_local = p.data_criacao
    if seed_changed:
        db.session.commit()

    usuarios = (
        User.query.filter(User.tipo != "admin").order_by(User.nome_completo).all()
    )

    # >>> envia a lista de equipamentos para o modal de edição
    equipamentos_disp = Equipment.query.order_by(Equipment.name).all()

    original_ids = {p.original_proposal_id or p.id for p in propostas.items}
    version_rows = []
    versions_by_original: dict[int, list[Proposal]] = {}
    if original_ids:
        version_rows = (
            Proposal.query.filter(
                or_(
                    Proposal.original_proposal_id.in_(original_ids),
                    Proposal.id.in_(original_ids),
                )
            )
            .order_by(Proposal.version_number.asc(), Proposal.data_criacao.asc())
            .all()
        )
    for version in version_rows:
        original_id = version.original_proposal_id or version.id
        if not version.version_number:
            version.version_number = 1
        if version.is_current is None:
            version.is_current = version.id in {p.id for p in propostas.items}
        if version.is_original is None:
            version.is_original = version.version_number == 1
        if version.data_criacao and version.data_criacao.tzinfo is None:
            version.data_criacao = version.data_criacao.replace(tzinfo=timezone.utc)
        if version.data_criacao:
            version.data_criacao_local = version.data_criacao.astimezone(LOCAL_TZ)
        if version.approved_at:
            if version.approved_at.tzinfo is None:
                version.approved_at = version.approved_at.replace(tzinfo=timezone.utc)
            version.approved_at_local = version.approved_at.astimezone(LOCAL_TZ)
        versions_by_original.setdefault(original_id, []).append(version)

    return render_template(
        "historico_propostas.html",
        propostas=propostas,
        usuarios_list=usuarios,
        servico_sel=serv_filter,
        modalidade_sel=mod_filter,
        issuer_sel=issuer_filter,
        issuer_options=ISSUER_COMPANY_CHOICES,
        system_options=_system_options_payload(),
        user_sel=user_filter,
        date_sel=data_filter,
        empresa_sel=company_filter,
        empresa_options=empresa_options,
        ServicoType=ServicoType,
        ModalidadeType=ModalidadeType,
        ParamOption=ParamOption,
        ParamCategory=ParamCategory,
        equipments=equipamentos_disp,  # <<< necessário para popular o <select> do modal
        versions_by_original=versions_by_original,
    )

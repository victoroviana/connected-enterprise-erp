
"""Helpers e definições para orçamentos da assistência técnica."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, Iterable
import html

from modules.propostas.gerar_proposta import _to_file_url
from modules.propostas.models import Part


OBSERVACAO_PADRAO = (
    "Após análise técnica, havendo a necessidade da substituição de peças não "
    "inclusas neste orçamento, o técnico responsável pelo atendimento poderá "
    "informar os valores \"in loco\", diretamente ao responsável da empresa "
    "que estiver acompanhando a visita, para a sua devida aprovação. Os valores "
    "aprovados serão cobrados à parte."
)


def _load_orcamento_definitions(*, active_only: bool = True) -> dict[str, dict[str, Any]]:
    from modules.suporte.models import OrcamentoTemplate

    try:
        query = OrcamentoTemplate.query
        if active_only:
            query = query.filter_by(ativo=True)
        templates = query.order_by(OrcamentoTemplate.id).all()
    except RuntimeError:
        return {}
    return {template.chave: template.to_dict() for template in templates}


class OrcamentoDefinitions(Mapping[str, dict[str, Any]]):
    """Backwards-compatible view over the database-backed budget templates."""

    def _data(self) -> dict[str, dict[str, Any]]:
        return _load_orcamento_definitions()

    def __getitem__(self, key: str) -> dict[str, Any]:
        return self._data()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def get(self, key: str, default: Any = None) -> Any:
        return self._data().get(key, default)


ORCAMENTO_DEFINITIONS: Mapping[str, dict[str, Any]] = OrcamentoDefinitions()


def list_orcamento_types() -> list[tuple[str, str]]:
    from modules.suporte.models import OrcamentoTemplate
    templates = OrcamentoTemplate.query.filter_by(ativo=True).order_by(OrcamentoTemplate.id).all()
    return [(t.chave, t.label or t.chave.title()) for t in templates]


def format_currency(value: float | int | None) -> str:
    num = float(value or 0.0)
    return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_currency(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = str(value).strip()
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace("R$", "").replace(" ", "")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_int(value: str | None) -> int:
    if value is None:
        return 0
    cleaned = str(value).strip()
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned))
        except ValueError:
            return 0


def parse_percent(value: str | None) -> float:
    if value is None:
        return 0.0
    cleaned = str(value).strip().replace("%", "")
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def build_orcamento_items(tipo: str, form_data: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    from modules.suporte.models import OrcamentoTemplate
    template = OrcamentoTemplate.query.filter_by(chave=tipo, ativo=True).first()
    if not template:
        return [], 0.0
    meta = template.to_dict()
    if not meta:
        return [], 0.0
    items = []
    total = 0.0
    indices = set()
    for key in form_data.keys():
        if key.startswith(f"equip_{tipo}_"):
            try:
                indices.add(int(key[len(f"equip_{tipo}_") :]))
            except ValueError:
                continue
        elif key.startswith(f"qty_{tipo}_"):
            try:
                indices.add(int(key[len(f"qty_{tipo}_") :]))
            except ValueError:
                continue
        elif key.startswith(f"unit_{tipo}_"):
            try:
                indices.add(int(key[len(f"unit_{tipo}_") :]))
            except ValueError:
                continue
        elif key.startswith(f"desc_{tipo}_"):
            try:
                indices.add(int(key[len(f"desc_{tipo}_") :]))
            except ValueError:
                continue

    defaults = meta.get("items", [])
    if not indices:
        indices = set(range(len(defaults)))
    for index in sorted(indices):
        default_item = defaults[index] if index < len(defaults) else {}
        equip_key = f"equip_{tipo}_{index}"
        desc_key = f"desc_{tipo}_{index}"
        qty_key = f"qty_{tipo}_{index}"
        unit_key = f"unit_{tipo}_{index}"
        disc_key = f"disc_{tipo}_{index}"

        equipment_id = parse_int(form_data.get(equip_key))
        equipment = Part.query.get(equipment_id) if equipment_id else None
        if equipment_id and not equipment:
            continue

        description = (form_data.get(desc_key) or "").strip()
        if not description and equipment:
            description = equipment.description or equipment.name or ""
        if not description:
            description = default_item.get("description", "")

        quantity = parse_int(form_data.get(qty_key))
        if form_data.get(qty_key) is None:
            quantity = int(default_item.get("default_qty", 0) or 0)
        unit_raw = form_data.get(unit_key)
        unit_price = parse_currency(unit_raw)
        if unit_raw is None or not str(unit_raw).strip():
            if equipment and equipment.unit_price is not None:
                unit_price = float(equipment.unit_price)
            else:
                unit_price = float(default_item.get("unit_price", 0.0))
        discount_percent = parse_percent(form_data.get(disc_key))

        if not description and quantity > 0:
            description = "Item adicional"

        if not description and quantity <= 0:
            continue

        line_total = float(quantity) * float(unit_price) * (1 - (discount_percent / 100.0))
        total += line_total
        image = None
        if equipment and equipment.illustration_path:
            image = _to_file_url(equipment.illustration_path)
        items.append(
            {
                "key": default_item.get("key", f"item_{index}"),
                "equipment_id": equipment_id or None,
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_percent": discount_percent,
                "total_price": line_total,
                "image": image,
            }
        )
    return items, total


def build_snapshot(task) -> dict[str, Any]:
    if not task:
        return {
            "empresa": "Avulso (Sem OS)",
            "cnpj": "",
            "client_name": "",
            "telefone": "",
            "email": "",
            "os": "AVULSO",
            "unidade": "Sem Unidade",
            "departamento": "N/A",
            "descricao": "Orçamento sem OS vinculada",
            "tecnico": "N/A",
            "data_criacao": None,
        }
    return {
        "empresa": getattr(task, "nome", None),
        "cnpj": getattr(task, "cnpj", None),
        "client_name": getattr(task, "client_name", None) or getattr(task, "nome", None) or "",
        "telefone": getattr(task, "telefone", None) or "",
        "email": getattr(task, "email", None) or "",
        "os": getattr(task, "OS", None) or getattr(task, "os", None),
        "unidade": getattr(task, "unidade", None),
        "departamento": getattr(task, "departamento_responsavel", None),
        "descricao": getattr(task, "descricao", None),
        "tecnico": getattr(task, "usuario_designado", None),
        "data_criacao": (
            task.data_criacao.isoformat() if getattr(task, "data_criacao", None) else None
        ),
    }


def build_orcamento_context(orcamento, *, issued_by: str | None = None) -> dict[str, Any]:
    from modules.suporte.models import OrcamentoTemplate
    template = OrcamentoTemplate.query.filter_by(chave=orcamento.tipo).first()
    meta = template.to_dict() if template else {}
    snapshot = orcamento.snapshot or {}
    items = []
    for item in orcamento.itens or []:
        items.append(
            {
                "description": item.get("description") or "",
                "quantity": int(item.get("quantity") or 0),
                "unit_price": format_currency(item.get("unit_price")),
                "discount_percent": float(item.get("discount_percent") or 0.0),
                "total_price": format_currency(item.get("total_price")),
                "image": item.get("image"),
            }
        )

    created_at = getattr(orcamento, "created_at", None)
    if isinstance(created_at, datetime):
        created_label = created_at.strftime("%d/%m/%Y")
    else:
        created_label = None

    os_code = snapshot.get("os") or ""
    orcamento_code = snapshot.get("numero_proposta") or os_code or str(orcamento.id)
    company = snapshot.get("empresa") or "-"
    cnpj = snapshot.get("cnpj") or ""
    client_name = snapshot.get("client_name") or company
    phone = snapshot.get("telefone") or "-"

    digits = "".join(c for c in cnpj if c.isdigit())
    if len(digits) == 11:
        doc_label = "CPF"
    elif len(digits) == 14:
        doc_label = "CNPJ"
    else:
        doc_label = "CNPJ" if cnpj else "Documento"

    issuer_name = current_app.config.get("COMPANY_NAME", "Empresa Matriz")
    issuer_email = current_app.config.get("COMPANY_EMAIL", "comercial@empresa.com.br")
    issuer_phone = current_app.config.get("COMPANY_PHONE", "11 3000-0000")
    issuer_site = current_app.config.get("COMPANY_SITE", "www.empresa.com.br")
    issuer_address = ""

    if "condicoes" in snapshot:
        condicoes = snapshot.get("condicoes") or []
    else:
        condicoes = meta.get("condicoes", [])
    if "observacao" in snapshot:
        observacao = snapshot.get("observacao")
    else:
        observacao = meta.get("observacao")
    if "aceite" in snapshot:
        aceite = snapshot.get("aceite") or []
    else:
        aceite = meta.get("aceite", [])
    return {
        "orcamento_label": meta.get("label", "Orçamento técnico"),
        "orcamento_table_title": meta.get("table_title", "Itens do orçamento"),
        "orcamento_code": orcamento_code,
        "data_criacao": created_label,
        "company": company,
        "cnpj": cnpj,
        "client_name": client_name,
        "client_document_label": doc_label,
        "client_document_value": cnpj or "-",
        "client_phone_display": phone,
        "email": snapshot.get("email") or "-",
        "os_code": os_code,
        "unidade": snapshot.get("unidade") or "-",
        "departamento": snapshot.get("departamento") or "-",
        "tecnico": snapshot.get("tecnico") or "Sem técnico",
        "descricao": snapshot.get("descricao") or "-",
        "items": items,
        "total_label": format_currency(getattr(orcamento, "total", 0.0)),
        "investimento_total": format_currency(getattr(orcamento, "total", 0.0)),
        "total_itens": len(items),
        "condicoes": condicoes,
        "observacao": observacao,
        "aceite": aceite,
        "issuer_company": issuer_name,
        "issuer_company_cnpj": "",
        "issuer_contact_name": issued_by or issuer_name,
        "issuer_email": issuer_email,
        "issuer_phone": issuer_phone,
        "issuer_phone_display": issuer_phone,
        "issuer_site": issuer_site,
        "issuer_address": issuer_address,
        "nome_colaborador": issued_by or issuer_name,
        "email_colaborador": issuer_email,
        "consultor_phone_list": [issuer_phone] if issuer_phone else [],
        "issuer_footer_lines": [line for line in (issuer_address, issuer_phone, issuer_site) if line],
        "logo_image": _to_file_url("static/images/sollus_logo.png"),
        "logo_image_dark": _to_file_url("static/images/sollus_logo.png"),
        "favicon_ico": _to_file_url("static/images/favicon.ico"),
        "favicon_png": _to_file_url("static/images/favicon.png"),
        "whatsapp_icon": _to_file_url("static/images/whatsapp.png"),
        "linkedin_icon": _to_file_url("static/images/linkedin.png"),
        "facebook_icon": _to_file_url("static/images/Facebook_Logo_2023.png"),
        "instagram_icon": _to_file_url("static/images/instagram.png"),
        "youtube_icon": _to_file_url("static/images/Youtube_logo.png"),
    }


def html_lines(text: str | None) -> str:
    if not text:
        return ""
    return "<br>".join(html.escape(line) for line in str(text).splitlines())


def iter_orcamento_items(tipo: str) -> Iterable[dict[str, Any]]:
    from modules.suporte.models import OrcamentoTemplate
    template = OrcamentoTemplate.query.filter_by(chave=tipo).first()
    meta = template.to_dict() if template else {}
    return meta.get("items", [])

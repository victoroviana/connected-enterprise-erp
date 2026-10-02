import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _digits(text: str | None) -> str:
    return "".join(filter(str.isdigit, text or ""))


def _format_cnpj(value: str | None) -> str:
    digits = _digits(value)
    if len(digits) != 14:
        return digits or ""
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _format_cpf(value: str | None) -> str:
    digits = _digits(value)
    if len(digits) != 11:
        return digits or ""
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _format_phone(value: str | None) -> str:
    digits = _digits(value)
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return value or ""


def _normalize_phone_list(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    phones = []
    for entry in values or []:
        if entry is None:
            continue
        cleaned = str(entry).strip()
        if cleaned:
            phones.append(cleaned)
    return phones


def _clean_phone(value: str | None) -> str:
    return _digits(value)


def _valid_phone(value: str | None) -> bool:
    return len(_digits(value)) >= 11


def _resolve_img_path(pth: str | None) -> str | None:
    if not pth:
        return None
    normalized = str(pth).strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return None
    candidates = []
    parts = [p for p in normalized.split("/") if p not in ("", ".", "..")]
    if parts:
        joined = "/".join(parts)
        candidates.extend([
            ROOT / joined,
            ROOT / "static" / joined,
            ROOT / "static" / "images" / joined,
        ])
        if len(parts) > 1 and parts[0].lower() == "static":
            trimmed = "/".join(parts[1:])
            candidates.append(ROOT / trimmed)
            candidates.append(ROOT / "static" / trimmed)
    for cand in candidates:
        if cand.exists():
            return str(cand.resolve())
    return None


def _to_file_url(path: str | None) -> str | None:
    abs_path = _resolve_img_path(path)
    if not abs_path:
        return None
    resolved = Path(abs_path)
    if sys.platform.startswith("win"):
        return "file:///" + str(resolved).replace("\\", "/")
    return "file://" + str(resolved)


def _fmt(value: float | int | str) -> str:
    number = float(value or 0)
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _is_system_row(eq_id) -> bool:
    return isinstance(eq_id, str) and eq_id.startswith("system:")


try:
    from platform_app import create_app  # type: ignore
    from modules.propostas.models import Proposal  # type: ignore
    from extensions import db  # type: ignore
    _HAS_APP = True
except Exception:
    create_app = None  # type: ignore
    Proposal = None  # type: ignore
    db = None  # type: ignore
    _HAS_APP = False

try:
    from modules.propostas.models import ServicoType, ModalidadeType  # type: ignore
    from modules.propostas.constants import DEFAULT_ISSUER_CODE, ISSUER_COMPANY_MAP  # type: ignore
    from modules.propostas.gerar_proposta import (
        _build_html_context as _context_builder,
        _convert_html_to_pdf as _html_to_pdf,
    )  # type: ignore
except Exception:
    DEFAULT_ISSUER_CODE = "sollus"
    ISSUER_COMPANY_MAP = {
        "sollus": {
            "name": "Sollus Tecnologia",
            "cnpj": "14.129.133/0001-77",
            "email": "comercial@sollusgroup.com",
            "phone": "21 2413-3203",
            "site": "sollusgroup.com",
            "address": "",
        }
    }

    class ServicoType:  # type: ignore
        PONTO = "PONTO"
        ACESSO = "ACESSO"

    class ModalidadeType:  # type: ignore
        AQUISICAO = "AQUISICAO"
        LOCACAO = "LOCACAO"

    def _context_builder(proposta, equipamentos, **kwargs):  # type: ignore
        tel_raw = kwargs.get("tel_raw") or getattr(proposta, "telefone", "") or ""
        tel_clean = kwargs.get("tel_clean") or _clean_phone(tel_raw)
        whatsapp_url = f"https://wa.me/{tel_clean}" if _valid_phone(tel_clean) else None

        client_company = getattr(proposta, "company", None) or "Empresa Teste"
        client_contact = getattr(proposta, "client_name", None) or "-"
        doc_digits = getattr(proposta, "cnpj", None) or ""
        doc_type = (getattr(proposta, "client_document_type", None) or "").lower()
        pure_digits = _digits(doc_digits)
        if doc_type not in {"cpf", "cnpj"}:
            doc_type = "cnpj" if len(pure_digits) == 14 else "cpf"
        if doc_type == "cpf":
            document_label = "CPF"
            document_value = _format_cpf(pure_digits)
        else:
            document_label = "CNPJ"
            document_value = _format_cnpj(pure_digits)

        nome_colaborador = kwargs.get("nome_colaborador") or getattr(proposta, "consultor_nome", "") or ""
        email_colaborador = kwargs.get("email_colaborador") or getattr(proposta, "consultor_email", "") or ""
        consultor_phone_input = kwargs.get("telefone_colaborador") or getattr(proposta, "consultor_phone", None)
        consultant_phone_values = _normalize_phone_list(consultor_phone_input)
        if not consultant_phone_values:
            consultant_phone_values = ["21 2413-3203"]
        consultor_phone_list = [_format_phone(value) for value in consultant_phone_values]
        consultor_phone = consultor_phone_list[0]

        equipamentos_render = []
        total_unico = 0.0
        total_mensal = 0.0
        for eq in equipamentos or []:
            pct = float(getattr(eq, "discount_percent", 0) or 0.0)
            cheio = float(getattr(eq, "unit_price", 0) or 0.0)
            qtd = int(getattr(eq, "quantity", 1) or 1)
            valor_com_desconto = cheio * (1 - pct / 100.0)
            override = getattr(eq, "total_override", None)
            subtotal = float(override) if override is not None else valor_com_desconto * qtd

            equipamentos_render.append(
                {
                    "description": getattr(eq, "description", None) or getattr(eq, "name", "") or "",
                    "image": _to_file_url(getattr(eq, "illustration_path", None)),
                    "quantity": qtd,
                    "unit_price": _fmt(cheio) if not _is_system_row(getattr(eq, "id", "")) else f"{_fmt(cheio)} (Mensal)",
                    "total_price": _fmt(subtotal) if not _is_system_row(getattr(eq, "id", "")) else f"{_fmt(subtotal)} (Mensal)",
                }
            )

            if _is_system_row(getattr(eq, "id", "")):
                total_mensal += subtotal
            else:
                total_unico += subtotal

        investimento_unico = _fmt(total_unico)
        investimento_mensal = _fmt(total_mensal) if total_mensal else None
        investimento_total = _fmt(total_unico + total_mensal)

        data_criacao = getattr(proposta, "data_criacao", None)
        data_fmt = data_criacao.strftime("%d/%m/%Y") if isinstance(data_criacao, datetime) else None

        servico_value = getattr(proposta, "servico_type", None)
        if isinstance(servico_value, str):
            servico_label = servico_value.title()
        else:
            servico_label = getattr(servico_value, "label", None) or getattr(servico_value, "name", None)

        modalidade_value = getattr(proposta, "modalidade_type", None)
        if isinstance(modalidade_value, str):
            modalidade_label = modalidade_value.title()
        else:
            modalidade_label = getattr(modalidade_value, "label", None) or getattr(modalidade_value, "name", None)

        condicoes = [
            ("Condicoes de Pagamento (Equipamento)", getattr(proposta, "pagamento", None)),
            ("Prazo de entrega", getattr(proposta, "prazo_entrega", None)),
            ("Frete", getattr(proposta, "frete", None)),
            ("Validade da Proposta", getattr(proposta, "validade", None)),
            ("Garantia do Equipamento", getattr(proposta, "garantia", None)),
            ("Garantia do Sistema", getattr(proposta, "garantia_sistema", None)),
        ]

        issuer_code = getattr(proposta, "issuer_company_code", None) or DEFAULT_ISSUER_CODE
        issuer_meta = ISSUER_COMPANY_MAP.get(issuer_code, ISSUER_COMPANY_MAP["sollus"])

        is_ponto = str(servico_value or "").upper() == "PONTO"
        observacoes = []
        if is_ponto:
            observacoes = [
                "Observacoes sobre o relogio de ponto:",
                "Equipamentos atendem a Portaria 671.",
                "Cada equipamento certificado pelo MTE (SREP) atende a um CNPJ.",
                "Uma vez cadastrado, o relogio nao pode ser reutilizado por outra empresa fora do mesmo grupo.",
            ]

        telefone_formatado = _format_phone(tel_raw)

        return {
            "company": client_company,
            "client_name": client_contact,
            "cnpj": document_value,
            "client_document_label": document_label,
            "client_document_value": document_value,
            "email": getattr(proposta, "email", None) or "-",
            "telefone": telefone_formatado,
            "proposta_cod": kwargs.get("proposta_cod") or getattr(proposta, "filename", "") or "",
            "servico_label": servico_label,
            "modalidade_label": modalidade_label,
            "data_criacao": data_fmt,
            "equipamentos": equipamentos_render,
            "total_itens": len(equipamentos_render),
            "investimento_unico": investimento_unico,
            "investimento_mensal": investimento_mensal,
            "investimento_total": investimento_total,
            "condicoes": condicoes,
            "is_servico_ponto": is_ponto,
            "observacoes_ponto": observacoes,
            "nome_colaborador": nome_colaborador,
            "email_colaborador": email_colaborador,
            "whatsapp_url": whatsapp_url,
            "logo_image": _to_file_url("static/images/sollus_logo_white.png") or _to_file_url("static/images/sollus_logo.png"),
            "logo_image_light": _to_file_url("static/images/sollus_logo_white.png") or _to_file_url("static/images/sollus_logo.png"),
            "logo_image_dark": _to_file_url("static/images/sollus_logo.png"),
            "signature_image": _to_file_url("static/signatures/user_demo.png"),
            "issuer_company": issuer_meta.get("name", "Sollus Tecnologia"),
            "issuer_company_cnpj": _format_cnpj(issuer_meta.get("cnpj", "")),
            "issuer_email": issuer_meta.get("email", "comercial@sollusgroup.com"),
            "issuer_phone": _format_phone(issuer_meta.get("phone", "21 2413-3203")),
            "issuer_site": issuer_meta.get("site", "sollusgroup.com"),
            "issuer_address": issuer_meta.get("address", ""),
            "issuer_contact_name": nome_colaborador or issuer_meta.get("name", "Sollus Tecnologia"),
            "issuer_company_code": issuer_code,
            "consultor_phone": consultor_phone,
            "consultor_phone_list": consultor_phone_list,
            "client_phone_display": telefone_formatado,
            "client_whatsapp_url": whatsapp_url,
        }

    def _html_to_pdf(html: str) -> bytes:  # type: ignore
        from tempfile import TemporaryDirectory
        from playwright.sync_api import sync_playwright  # type: ignore

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            html_path = tmp_root / 'proposta.html'
            pdf_path = tmp_root / 'proposta.pdf'
            html_path.write_text(html, encoding='utf-8')

            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(html_path.as_uri(), wait_until='networkidle')
                        page.emulate_media(media='print')
                        page.pdf(
                            path=str(pdf_path),
                            format='A4',
                            print_background=True,
                            margin={'top': '10mm', 'right': '10mm', 'bottom': '10mm', 'left': '10mm'},
                        )
                    finally:
                        browser.close()
            except Exception as exc:
                raise RuntimeError('Falha ao gerar o PDF com Playwright (fallback).') from exc

            return pdf_path.read_bytes()


OUTPUT_BASE = Path("outputs")
OUT_MAIN = OUTPUT_BASE / "propostas"
OUT_VARIANTS = OUTPUT_BASE / "design_variants"

VARIANTS = {
    "aurora": "propostas/design_variants/aurora.html",
    "circuit": "propostas/design_variants/circuit.html",
    "minimal": "propostas/design_variants/minimal.html",
    "neon": "propostas/design_variants/neon.html",
    "prism": "propostas/design_variants/prism.html",
}


def _fallback_sample():
    items = [
        SimpleNamespace(
            description="Plataforma Sollus Connected",
            name="Sollus Connected",
            discount_percent=0,
            unit_price=280.0,
            quantity=1,
            illustration_path=None,
            total_override=None,
            id="system:sollus",
        ),
        SimpleNamespace(
            description="Totem biometrico de acesso",
            name="Totem biometrico",
            discount_percent=5,
            unit_price=6500.0,
            quantity=2,
            illustration_path="static/images/IdBlock_Next_1_facial_edit.jpg",
            total_override=None,
            id=101,
        ),
    ]
    proposta = SimpleNamespace(
        company="Empresa Teste",
        cnpj="00112233000199",
        client_document_type="cnpj",
        issuer_company_code=DEFAULT_ISSUER_CODE,
        client_name="Cliente Exemplo",
        email="cliente@sollus.com.br",
        telefone="+55 11 98888-7777",
        consultor_phone="+55 21 2413-3203",
        pagamento="30/60",
        prazo_entrega="20 dias uteis",
        frete="FOB",
        validade="25 dias",
        garantia="12 meses",
        garantia_sistema="Suporte remoto incluso",
        servico_type=ServicoType.PONTO,
        modalidade_type=ModalidadeType.AQUISICAO,
        data_criacao=datetime(2025, 1, 15),
        filename="PROP-EXEMPLO-001",
    )
    return proposta, items


def _load_latest_from_db():
    if not _HAS_APP or create_app is None or db is None or Proposal is None:
        return None
    try:
        app = create_app()
    except Exception:
        return None
    with app.app_context():  # type: ignore[attr-defined]
        try:
            proposta = (
                db.session.query(Proposal)  # type: ignore[arg-type]
                .order_by(Proposal.data_criacao.desc())
                .first()
            )
        except Exception:
            return None
        if not proposta:
            return None
        try:
            equipamentos = list(proposta.equipamentos)
        except Exception:
            equipamentos = []
        return proposta, equipamentos


def main() -> None:
    OUT_MAIN.mkdir(parents=True, exist_ok=True)
    OUT_VARIANTS.mkdir(parents=True, exist_ok=True)

    proposta_items = _load_latest_from_db()
    if proposta_items is None:
        proposta, items = _fallback_sample()
    else:
        proposta, items = proposta_items

    env = Environment(
        loader=FileSystemLoader((ROOT / "templates").as_posix()),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )

    tel_raw = getattr(proposta, "telefone", "")
    context = _context_builder(
        proposta,
        items,
        nome_colaborador="Consultor Sollus",
        email_colaborador="consultor@sollus.com.br",
        proposta_cod=getattr(proposta, "filename", "") or "PROP-DEMO-001",
        tel_raw=tel_raw,
        tel_clean=_clean_phone(tel_raw),
        telefone_colaborador=getattr(proposta, "consultor_phone", None),
    )

    main_template = "propostas/design_variants/circuit.html"
    html_main = env.get_template(main_template).render(**context)
    (OUT_MAIN / "proposta.html").write_text(html_main, encoding="utf-8")
    try:
        pdf_data = _html_to_pdf(html_main)
        (OUT_MAIN / "proposta.pdf").write_bytes(pdf_data)
    except Exception as exc:
        (OUT_MAIN / "proposta.txt").write_text(f"Falha ao gerar PDF: {exc}", encoding="utf-8")

    for name, template in VARIANTS.items():
        html = env.get_template(template).render(**context)
        (OUT_VARIANTS / f"{name}.html").write_text(html, encoding="utf-8")
        try:
            pdf_data = _html_to_pdf(html)
            (OUT_VARIANTS / f"{name}.pdf").write_bytes(pdf_data)
        except Exception as exc:
            (OUT_VARIANTS / f"{name}.txt").write_text(f"Falha ao gerar PDF: {exc}", encoding="utf-8")

    print(f"Arquivos gerados em: {OUT_MAIN.resolve()} e {OUT_VARIANTS.resolve()}")


if __name__ == "__main__":
    main()


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_app import create_app
from modules.propostas.gerar_proposta import (
    _build_html_context,
    _convert_html_to_pdf,
)
from modules.propostas.models import ServicoType, ModalidadeType
from types import SimpleNamespace

OUTPUT_DIR = Path('outputs/design_variants')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VARIANTS = {
    'aurora': 'propostas/design_variants/aurora.html',
    'circuit': 'propostas/design_variants/circuit.html',
    'minimal': 'propostas/design_variants/minimal.html',
    'neon': 'propostas/design_variants/neon.html',
    'prism': 'propostas/design_variants/prism.html',
}

sample_items = [
    SimpleNamespace(
        description='Plataforma Sollus Connected',
        name='Sollus Connected',
        discount_percent=0,
        unit_price=280.0,
        quantity=1,
        illustration_path=None,
        total_override=None,
        id='system:sollus'
    ),
    SimpleNamespace(
        description='Totem biomtrico de acesso',
        name='Totem biomtrico',
        discount_percent=5,
        unit_price=6500.0,
        quantity=2,
        illustration_path=None,
        total_override=None,
        id=101
    ),
]

sample_proposta = SimpleNamespace(
    company='Sollus Tecnologia',
    cnpj='00.000.000/0000-00',
    client_name='Cliente Exemplo',
    email='cliente@sollus.com.br',
    telefone='+55 11 98888-7777',
    pagamento='30/60',
    prazo_entrega='20 dias teis',
    frete='FOB',
    validade='25 dias',
    garantia='12 meses',
    garantia_sistema='Suporte remoto incluso',
    servico_type=ServicoType.PONTO,
    modalidade_type=ModalidadeType.AQUISICAO,
    data_criacao=None,
    filename='PROP-2025-001',
    sistema_ativo=True,
    sistema_nome='Sistema Sollus',
    sistema_descricao='Soluo conectada para controle de acesso e ponto',
    sistema_imagem='',
    sistema_quantidade=1,
    sistema_preco_unitario=280.0,
    sistema_preco_total=280.0,
)

app = create_app()

with app.app_context():
    context = _build_html_context(
        sample_proposta,
        sample_items,
        nome_colaborador='Consultor Sollus',
        email_colaborador='consultor@sollus.com.br',
        proposta_cod='001/2025',
        tel_raw=sample_proposta.telefone,
        tel_clean='5511988887777',
    )

    for variant, template in VARIANTS.items():
        html = app.jinja_env.get_template(template).render(**context)
        html_path = OUTPUT_DIR / f'{variant}.html'
        html_path.write_text(html, encoding='utf-8')
        try:
            pdf_data = _convert_html_to_pdf(html)
            (OUTPUT_DIR / f'{variant}.pdf').write_bytes(pdf_data)
        except Exception as exc:  # pragma: no cover
            (OUTPUT_DIR / f'{variant}.txt').write_text(f'Falha ao gerar PDF: {exc}', encoding='utf-8')

print(f'Pr-visualizaes salvas em {OUTPUT_DIR.resolve()}')

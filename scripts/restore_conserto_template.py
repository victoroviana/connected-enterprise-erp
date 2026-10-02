import sys
sys.path.insert(0, '/home/sollus/sollus_connected')
from platform_app import create_app
from modules.suporte.models import OrcamentoTemplate
from extensions import db

app = create_app()
with app.app_context():
    existing = OrcamentoTemplate.query.filter_by(chave='conserto').first()
    if existing:
        print(f"Template conserto already exists with ID: {existing.id}")
    else:
        template = OrcamentoTemplate(
            id=1,
            chave='conserto',
            label='Orçamento de conserto',
            table_title='OPÇÃO | ORÇAMENTO CONSERTO',
            items=[],
            condicoes=[
                ['Condições de Pagamento', '14 DD'],
                ['Validade da Proposta', '20 dias'],
                ['Garantia', '03 meses (para esse atendimento)']
            ],
            observacao='Após análise técnica, havendo a necessidade da substituição de peças não inclusas neste orçamento, o técnico responsável pelo atendimento poderá informar os valores "in loco", diretamente ao responsável da empresa que estiver acompanhando a visita, para a sua devida aprovação. Os valores aprovados serão cobrados à parte.',
            aceite=['OPÇÃO: ORÇAMENTO DE CONSERTO'],
            ativo=True
        )
        db.session.add(template)
        db.session.commit()
        print(f"Template conserto RESTORED successfully with ID: {template.id}")

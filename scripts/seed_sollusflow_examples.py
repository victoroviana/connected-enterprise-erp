# scripts/seed_sollusflow_examples.py
import sys
from datetime import date, datetime, timedelta
sys.path.insert(0, ".")

from platform_app import create_app
from extensions import db
from modules.propostas.models import User
from modules.chamados.models import (
    SfPedido,
    SfFaseHistorico,
    SfChecklist,
    SfObservacao,
    SF_FASES,
)
from modules.chamados.blueprints.central_conhecimento.routes import _CHECKLIST_PADRAO

app = create_app()
with app.app_context():
    print("--- Semeando 5+ exemplos no SollusFlow ---")
    
    # Buscar usuarios de referencia
    u_victor = User.query.filter_by(usuario="victor.viana").first()
    u_jaqueline = User.query.filter_by(usuario="jaqueline.pereira").first()
    u_alexandre = User.query.filter_by(usuario="alexandre.cavalcante").first()
    u_roseli = User.query.filter_by(usuario="roseli.guedes").first()
    u_rodolfo = User.query.filter_by(usuario="rodolfo.dantas").first()
    u_weverson = User.query.filter_by(usuario="weverson.paulo").first()
    
    admin_id = (u_victor or u_alexandre or User.query.first()).id
    jaq_id = u_jaqueline.id if u_jaqueline else admin_id
    alex_id = u_alexandre.id if u_alexandre else admin_id
    roseli_id = u_roseli.id if u_roseli else admin_id
    rodolfo_id = u_rodolfo.id if u_rodolfo else admin_id
    weverson_id = u_weverson.id if u_weverson else admin_id
    victor_id = u_victor.id if u_victor else admin_id

    hoje = date.today()
    
    # Lista de 5 exemplos ricos e variados
    exemplos = [
        {
            "numero_pedido": "PED-2026-001",
            "cliente_nome": "TECH CORP SOLUCOES DIGITAIS LTDA",
            "cliente_cnpj": "12.345.678/0001-90",
            "tipo": "venda",
            "valor": 4850.00,
            "consultor_id": jaq_id,
            "responsavel_id": victor_id,
            "fase_atual": 1,
            "prioridade": "normal",
            "status": "ativo",
            "data_entrada": hoje,
            "data_prevista": hoje + timedelta(days=4), # Prazo futuro (OK)
            "descricao": "Venda de 2 Relogios de Ponto iDClass com bobinas de 400m e nobreak. Cliente solicitou prioridade normal para filial RJ.",
            "historico": [
                (None, 1, jaq_id, None, "Solicitacao recebida via WhatsApp com proposta assinada em anexo."),
            ],
            "checklists_done": {1: [0]}, # primeiro item concluido
            "observacoes": [
                (victor_id, "Pedido inserido no fluxo. Documentacao basica ja anexada ao chamado."),
            ]
        },
        {
            "numero_pedido": "PED-2026-002",
            "cliente_nome": "CONDOMINIO DO EDIFICIO AMADEUS",
            "cliente_cnpj": "04.892.115/0001-33",
            "tipo": "contrato",
            "valor": 1290.00,
            "consultor_id": alex_id,
            "responsavel_id": rodolfo_id,
            "fase_atual": 4,
            "prioridade": "alta",
            "status": "ativo",
            "data_entrada": hoje - timedelta(days=3),
            "data_prevista": hoje, # Vence HOJE (Badge Amarelo Hoje)
            "descricao": "Locacao de Catraca Flap com leitor facial e biometria. Equipamento necessita de revisao na bancada da oficina antes da reserva.",
            "historico": [
                (None, 1, alex_id, None, "Entrada da solicitacao de locacao."),
                (1, 2, roseli_id, None, "Documentacao do sindico e ata de assembleia conferidas."),
                (2, 3, roseli_id, None, "Cliente cadastrado no Base ERP sob codigo 1409."),
                (3, 4, victor_id, rodolfo_id, "Transferido para a oficina tecnica para inspecao e reserva da catraca."),
            ],
            "checklists_done": {1: [0, 1, 2], 2: [0, 1, 2], 3: [0, 1], 4: [0]},
            "observacoes": [
                (roseli_id, "Aprovacao da diretoria confirmada. Contrato padrão de 24 meses."),
                (rodolfo_id, "Catraca separada na bancada 3. Aguardando teste da placa controladora."),
            ]
        },
        {
            "numero_pedido": "PED-2026-003",
            "cliente_nome": "GRC SUCATAS AMBIENTAL LTDA",
            "cliente_cnpj": "33.104.567/0001-82",
            "tipo": "venda",
            "valor": 12800.00,
            "consultor_id": jaq_id,
            "responsavel_id": roseli_id,
            "fase_atual": 6,
            "prioridade": "urgente",
            "status": "ativo",
            "data_entrada": hoje - timedelta(days=7),
            "data_prevista": hoje - timedelta(days=2), # ATRASADO ha 2 dias (Badge Vermelho Atrasado)
            "descricao": "Venda de 4 Catracas Lumen e Software Sollus Enterprise. Cliente informou que enviaria comprovante do sinal de 50% via Pix.",
            "historico": [
                (None, 1, jaq_id, None, "Solicitacao de venda de grande porte inserida."),
                (1, 2, roseli_id, None, "CNPJ ativo e certidoes negativas aprovadas."),
                (2, 3, roseli_id, None, "Cadastro gerado no Base ERP."),
                (3, 4, rodolfo_id, None, "Equipamentos verificados no estoque central."),
                (4, 5, jaq_id, None, "Contrato de venda formalizado."),
                (5, 6, jaq_id, roseli_id, "Transferido ao Financeiro para validar comprovante de entrada."),
            ],
            "checklists_done": {1: [0, 1, 2], 2: [0, 1, 2], 3: [0, 1], 4: [0, 1], 5: [0, 1], 6: []},
            "observacoes": [
                (roseli_id, "Cobrado o financeiro da GRC no dia 02/09. Informaram que a diretoria liberaria o pagamento hoje."),
                (jaq_id, "Falei com o comprador Sr. Marcio, pagamento sera liquidado ate as 16h."),
            ]
        },
        {
            "numero_pedido": "PED-2026-004",
            "cliente_nome": "KATRIUM INDUSTRIAS QUIMICAS S.A.",
            "cliente_cnpj": "28.789.998/0001-74",
            "tipo": "contrato",
            "valor": 8500.00,
            "consultor_id": alex_id,
            "responsavel_id": weverson_id,
            "fase_atual": 10,
            "prioridade": "alta",
            "status": "ativo",
            "data_entrada": hoje - timedelta(days=15),
            "data_prevista": hoje + timedelta(days=6), # No prazo (Badge Verde)
            "descricao": "Implantacao de controle de acesso para 3 portarias com 6 leitores faciais. Infraestrutura civil e de rede liberadas pelo cliente.",
            "historico": [
                (None, 1, alex_id, None, "Entrada do projeto Katrium."),
                (1, 2, roseli_id, None, "Contrato e procuracoes validados."),
                (2, 3, roseli_id, None, "Cadastro validado no Base ERP."),
                (3, 4, rodolfo_id, None, "Terminais faciais reservados com sucesso."),
                (4, 5, alex_id, None, "Contrato assinado digitalmente."),
                (5, 6, roseli_id, None, "Sinal financeiro identificado."),
                (6, 7, rodolfo_id, None, "Equipamentos conferidos e embalados."),
                (7, 8, alex_id, None, "Copia assinada enviada."),
                (8, 9, weverson_id, None, "Formulario de instalacao respondido pelo TI do cliente."),
                (9, 10, victor_id, weverson_id, "Transferido para agendamento da equipe externa."),
            ],
            "checklists_done": {
                1: [0, 1, 2], 2: [0, 1, 2], 3: [0, 1], 4: [0, 1], 5: [0, 1],
                6: [0, 1], 7: [0, 1], 8: [0, 1], 9: [0, 1], 10: [0, 1]
            },
            "observacoes": [
                (weverson_id, "Instalacao agendada com o encarregado Jorge para a proxima terca-feira as 09:00."),
                (weverson_id, "Tecnicos escalados: Leandro Monteiro e Marco Antonio."),
            ]
        },
        {
            "numero_pedido": "PED-2026-005",
            "cliente_nome": "PANIFICACAO E CONFEITARIA RECREIO DO CRUZEIRO LTDA",
            "cliente_cnpj": "18.234.901/0001-45",
            "tipo": "venda",
            "valor": 3400.00,
            "consultor_id": jaq_id,
            "responsavel_id": victor_id,
            "fase_atual": 13,
            "prioridade": "normal",
            "status": "concluido", # CONCLUIDO
            "data_entrada": hoje - timedelta(days=20),
            "data_prevista": hoje - timedelta(days=5),
            "descricao": "Venda e implantacao completa de Relogio de Ponto MiniPrint e 1.000 crachas de proximidade. Processo 100% finalizado e cliente treinado.",
            "historico": [
                (None, 1, jaq_id, None, "Criacao do pedido."),
                (1, 5, jaq_id, None, "Aprovacao direta de documentacao e contrato."),
                (5, 6, roseli_id, None, "Pagamento a vista via Pix confirmado."),
                (6, 11, roseli_id, None, "NF e O.S emitidas."),
                (11, 12, weverson_id, None, "Acesso ao software Sollus Ponto liberado."),
                (12, 13, victor_id, None, "E-mail de boas-vindas enviado e pedido concluido com sucesso!"),
            ],
            "checklists_done": {
                1: [0, 1, 2], 2: [0, 1, 2], 3: [0, 1], 4: [0, 1], 5: [0, 1],
                6: [0, 1], 7: [0, 1], 8: [0, 1], 9: [0, 1], 10: [0, 1],
                11: [0, 1], 12: [0, 1], 13: [0, 1]
            },
            "observacoes": [
                (victor_id, "Treinamento realizado via Teams com a administradora Carla. Equipamento homologado na portaria 671."),
                (victor_id, "Cliente satisfeito. Processo concluido!"),
            ]
        },
        {
            "numero_pedido": "PED-2026-006",
            "cliente_nome": "ESSENTIAL CENTRO DE TREINAMENTO LTDA",
            "cliente_cnpj": "45.981.234/0001-12",
            "tipo": "venda",
            "valor": 2100.00,
            "consultor_id": alex_id,
            "responsavel_id": alex_id,
            "fase_atual": 2,
            "prioridade": "baixa",
            "status": "cancelado", # CANCELADO
            "data_entrada": hoje - timedelta(days=10),
            "data_prevista": hoje - timedelta(days=7),
            "descricao": "Venda de software avulso. Cliente desistiu da compra devido a corte de orcamento interno da empresa.",
            "historico": [
                (None, 1, alex_id, None, "Solicitacao inicial inserida."),
                (1, 2, roseli_id, None, "Cliente solicitou cancelamento antes da confeccao do contrato."),
            ],
            "checklists_done": {1: [0, 1, 2], 2: []},
            "observacoes": [
                (alex_id, "Cancelamento solicitado pelo cliente via e-mail. Nao houve faturamento."),
            ]
        }
    ]

    for ex in exemplos:
        # Verificar se ja existe
        existente = SfPedido.query.filter_by(numero_pedido=ex["numero_pedido"]).first()
        if existente:
            print(f"Pedido {ex['numero_pedido']} ja existe. Pulando...")
            continue
            
        pedido = SfPedido(
            numero_pedido=ex["numero_pedido"],
            cliente_nome=ex["cliente_nome"],
            cliente_cnpj=ex["cliente_cnpj"],
            tipo=ex["tipo"],
            valor=ex["valor"],
            consultor_id=ex["consultor_id"],
            responsavel_id=ex["responsavel_id"],
            fase_atual=ex["fase_atual"],
            prioridade=ex["prioridade"],
            data_entrada=ex["data_entrada"],
            data_prevista=ex["data_prevista"],
            status=ex["status"],
            descricao=ex["descricao"],
        )
        db.session.add(pedido)
        db.session.flush()
        
        # Inserir historico
        for h in ex["historico"]:
            hist = SfFaseHistorico(
                pedido_id=pedido.id,
                fase_de=h[0],
                fase_para=h[1],
                usuario_id=h[2],
                transferido_para_id=h[3],
                observacao=h[4],
                created_at=datetime.utcnow() - timedelta(days=ex["fase_atual"] - h[1] if h[1] else 0)
            )
            db.session.add(hist)
            
        # Inserir checklists para as fases relevantes
        max_fase = max(ex["fase_atual"], 1)
        for f in range(1, max_fase + 1):
            padrao = _CHECKLIST_PADRAO.get(f, [])
            done_indices = ex["checklists_done"].get(f, [])
            for pos, tit in enumerate(padrao):
                is_done = pos in done_indices
                item = SfChecklist(
                    pedido_id=pedido.id,
                    fase=f,
                    titulo=tit,
                    concluido=is_done,
                    concluido_por_id=ex["responsavel_id"] if is_done else None,
                    concluido_at=datetime.utcnow() if is_done else None,
                    posicao=pos,
                )
                db.session.add(item)
                
        # Inserir observacoes
        for autor_id, corpo in ex["observacoes"]:
            obs = SfObservacao(
                pedido_id=pedido.id,
                autor_id=autor_id,
                corpo=corpo,
            )
            db.session.add(obs)
            
        print(f"Criado com sucesso: {pedido.numero_pedido} - {pedido.cliente_nome} (Fase {pedido.fase_atual}, Status {pedido.status}, Prioridade {pedido.prioridade})")

    db.session.commit()
    print("--- Concluido com sucesso! ---")

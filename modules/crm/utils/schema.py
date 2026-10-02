"""Database compatibility and startup schema evolution for Sollus CRM."""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any

from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmOrigem,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing,
    CrmMotivoPerda,
    CrmRegraAutomacao,
    CrmRoletaConsultor,
    CrmWebhook,
    CrmWebhookLog,
    CrmTemplateMensagem,
    CrmRegraDistribuicao,
    CrmEquipamentoHistoricoPreco,
    CrmSoftwareHistoricoPreco,
)
from modules.propostas.models import SoftwarePlan

CRM_MODELS = [
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmOrigem,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing,
    CrmMotivoPerda,
    CrmRegraAutomacao,
    CrmRoletaConsultor,
    CrmWebhook,
    CrmWebhookLog,
    CrmTemplateMensagem,
    CrmRegraDistribuicao,
    CrmEquipamentoHistoricoPreco,
    CrmSoftwareHistoricoPreco,
    SoftwarePlan,
]

CRM_COLUMN_ALTERS: dict[str, dict[str, str]] = {
    "crm_negociacoes": {
        "data_estimada_fechamento": "ALTER TABLE crm_negociacoes ADD COLUMN data_estimada_fechamento DATE",
        "motivo_perda_id": "ALTER TABLE crm_negociacoes ADD COLUMN motivo_perda_id INTEGER",
        "motivo_perda_categoria": "ALTER TABLE crm_negociacoes ADD COLUMN motivo_perda_categoria VARCHAR(64)",
        "probabilidade": "ALTER TABLE crm_negociacoes ADD COLUMN probabilidade FLOAT",
        "origem_id": "ALTER TABLE crm_negociacoes ADD COLUMN origem_id INTEGER",
        "canal_origem": "ALTER TABLE crm_negociacoes ADD COLUMN canal_origem VARCHAR(64)",
        "temperatura": "ALTER TABLE crm_negociacoes ADD COLUMN temperatura VARCHAR(20)",
        "canal_preferencial": "ALTER TABLE crm_negociacoes ADD COLUMN canal_preferencial VARCHAR(32)",
        "necessidade": "ALTER TABLE crm_negociacoes ADD COLUMN necessidade VARCHAR(255)",
        "nivel_interesse": "ALTER TABLE crm_negociacoes ADD COLUMN nivel_interesse VARCHAR(32)",
        "fonte_lead": "ALTER TABLE crm_negociacoes ADD COLUMN fonte_lead VARCHAR(64)",
        "localidade_lead": "ALTER TABLE crm_negociacoes ADD COLUMN localidade_lead VARCHAR(120)",
        "satisfacao_cliente": "ALTER TABLE crm_negociacoes ADD COLUMN satisfacao_cliente INTEGER",
        "pos_venda_obs": "ALTER TABLE crm_negociacoes ADD COLUMN pos_venda_obs TEXT",
        "pos_venda_preenchido_por": "ALTER TABLE crm_negociacoes ADD COLUMN pos_venda_preenchido_por VARCHAR(120)",
        "pos_venda_em": "ALTER TABLE crm_negociacoes ADD COLUMN pos_venda_em DATETIME",
        "pausado_em": "ALTER TABLE crm_negociacoes ADD COLUMN pausado_em DATETIME",
        "pausado_motivo": "ALTER TABLE crm_negociacoes ADD COLUMN pausado_motivo VARCHAR(255)",
    },
    "crm_empresas": {
        "porte": "ALTER TABLE crm_empresas ADD COLUMN porte VARCHAR(64)",
        "numero_funcionarios": "ALTER TABLE crm_empresas ADD COLUMN numero_funcionarios INTEGER",
    },
    "crm_etapas": {
        "probabilidade": "ALTER TABLE crm_etapas ADD COLUMN probabilidade FLOAT DEFAULT 10.0",
    },
}

DEFAULT_ORIGENS = [
    ("Busca Paga Google", "google_ads", 1),
    ("Busca Orgânica Google", "organico", 2),
    ("Indicação", "indicacao", 3),
    ("Telefone", "telefone", 4),
    ("WhatsApp", "whatsapp", 5),
    ("Site Sollus", "site", 6),
    ("Ativa Licitações", "licitacao", 7),
    ("Facebook Ads", "facebook_ads", 8),
]

DEFAULT_MOTIVOS_PERDA = [
    ("Preço / Fora do Orçamento", "preco", 1),
    ("Optou por Concorrente", "concorrente", 2),
    ("Sem Contato / Desistência", "sem_contato", 3),
    ("Descarte / Sem Perfil", "descarte", 4),
    ("Outro Motivo", "outros", 5),
]

DEFAULT_TEMPLATES = [
    (
        "1º Contato SDR",
        "Olá {nome_contato}, tudo bem? Sou o {consultor} da Sollus Tecnologia. Recebemos seu interesse para a {empresa}. Quando poderíamos conversar por 5 minutos?",
    ),
    (
        "Follow-up Proposta",
        "Olá {nome_contato}! Aqui é o {consultor} da Sollus. Gostaria de saber se conseguiu avaliar a proposta comercial que enviamos para a {empresa}: {link_proposta}. Ficou alguma dúvida técnica ou comercial?",
    ),
    (
        "Retomada de Contato",
        "Olá {nome_contato}, como vão as coisas na {empresa}? Passando para saber se ainda está nos planos a implantação do sistema. Temos condições especiais!",
    ),
]


def ensure_crm_schema(app: Any = None) -> None:
    """
    Inspeciona e garante não-destrutivamente que todas as tabelas e colunas do CRM
    estejam presentes no banco de dados na inicialização da aplicação.
    """
    try:
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
    except Exception as exc:
        if app and hasattr(app, "logger"):
            app.logger.warning(f"Could not inspect database for CRM schema: {exc}")
        return

    # 1. Cria tabelas faltantes
    for model in CRM_MODELS:
        table_name = model.__tablename__
        if table_name not in existing_tables:
            with suppress(Exception):
                model.__table__.create(db.engine, checkfirst=True)
                existing_tables.add(table_name)

    # 2. Adiciona colunas faltantes em tabelas existentes
    for table_name, columns_dict in CRM_COLUMN_ALTERS.items():
        if table_name in existing_tables:
            try:
                table_cols = {col["name"] for col in inspector.get_columns(table_name)}
            except Exception:
                table_cols = set()

            for col_name, alter_sql in columns_dict.items():
                if col_name not in table_cols:
                    try:
                        db.session.execute(text(alter_sql))
                        db.session.commit()
                    except (OperationalError, Exception):
                        db.session.rollback()

    # 3. Seed de motivos de perda se vazio
    if "crm_motivos_perda" in existing_tables:
        try:
            if CrmMotivoPerda.query.count() == 0:
                for nome, categoria, ordem in DEFAULT_MOTIVOS_PERDA:
                    motivo = CrmMotivoPerda(
                        nome=nome,
                        categoria=categoria,
                        ordem=ordem,
                        ativo=True,
                    )
                    db.session.add(motivo)
                db.session.commit()
        except Exception:
            db.session.rollback()

    # 4. Seed de templates de mensagens se vazio
    if "crm_templates_mensagens" in existing_tables:
        try:
            if CrmTemplateMensagem.query.count() == 0:
                for nome, conteudo in DEFAULT_TEMPLATES:
                    template = CrmTemplateMensagem(
                        nome=nome,
                        conteudo=conteudo,
                        ativo=True,
                    )
                    db.session.add(template)
                db.session.commit()
        except Exception:
            db.session.rollback()

    # 5. Seed de origens comerciais se vazio
    if "crm_origens" in existing_tables:
        try:
            if CrmOrigem.query.count() == 0:
                for nome, canal, ordem in DEFAULT_ORIGENS:
                    origem = CrmOrigem(
                        nome=nome,
                        canal=canal,
                        ordem=ordem,
                        ativo=True,
                    )
                    db.session.add(origem)
                db.session.commit()
        except Exception:
            db.session.rollback()

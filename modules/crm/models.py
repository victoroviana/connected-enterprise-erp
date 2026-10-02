"""Modelos do banco de dados para o módulo Sollus CRM."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from extensions import db


class CrmFunil(db.Model):
    """Pipeline / Funil de Vendas."""
    __tablename__ = "crm_funis"

    id = db.Column(db.String(64), primary_key=True)  # ex: funil_ponto, funil_acesso, assistencia_tecnica
    nome = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=True, index=True)
    tipo = db.Column(db.String(64), default="ponto", nullable=False)  # ponto, acesso, assistencia, padrao
    descricao = db.Column(db.String(255), nullable=True)
    ordem = db.Column(db.Integer, default=0, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    cor = db.Column(db.String(32), default="#2563eb", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    etapas = db.relationship(
        "CrmEtapa",
        backref="funil",
        cascade="all, delete-orphan",
        order_by="CrmEtapa.ordem",
        lazy="joined"
    )
    negociacoes = db.relationship("CrmNegociacao", backref="funil", lazy="dynamic")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "slug": self.slug or "",
            "tipo": self.tipo or "padrao",
            "descricao": self.descricao,
            "ordem": self.ordem,
            "ativo": self.ativo,
            "cor": self.cor,
            "total_etapas": len(self.etapas) if self.etapas else 0
        }


class CrmEtapa(db.Model):
    """Etapa de um funil (coluna no Kanban)."""
    __tablename__ = "crm_etapas"

    id = db.Column(db.String(64), primary_key=True)
    funil_id = db.Column(db.String(64), db.ForeignKey("crm_funis.id", ondelete="CASCADE"), nullable=False, index=True)
    nome = db.Column(db.String(120), nullable=False)
    nickname = db.Column(db.String(10), nullable=True)
    ordem = db.Column(db.Integer, default=0, nullable=False, index=True)
    tipo = db.Column(db.String(20), default="normal", nullable=False)  # normal, ganho, perdido
    cor = db.Column(db.String(32), default="#64748b", nullable=False)
    probabilidade = db.Column(db.Float, default=10.0, nullable=False)

    negociacoes = db.relationship(
        "CrmNegociacao",
        backref="etapa",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "funil_id": self.funil_id,
            "nome": self.nome,
            "nickname": self.nickname,
            "ordem": self.ordem,
            "tipo": self.tipo,
            "cor": self.cor,
            "probabilidade": self.probabilidade if self.probabilidade is not None else 10.0
        }


class CrmEmpresa(db.Model):
    """Empresa / Organização comercial."""
    __tablename__ = "crm_empresas"

    id = db.Column(db.String(64), primary_key=True)
    nome = db.Column(db.String(255), nullable=False, index=True)
    cnpj = db.Column(db.String(32), nullable=True, index=True)
    segmento = db.Column(db.String(120), nullable=True)
    endereco = db.Column(db.Text, nullable=True)
    telefone = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    site = db.Column(db.String(255), nullable=True)
    porte = db.Column(db.String(64), nullable=True)
    numero_funcionarios = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_name = db.Column(db.String(120), nullable=True)
    
    total_ganho = db.Column(db.Integer, default=0, nullable=False)
    total_perdido = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    contatos = db.relationship("CrmContato", backref="empresa", lazy="dynamic", cascade="all, delete-orphan")
    negociacoes = db.relationship("CrmNegociacao", backref="empresa", lazy="dynamic")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "cnpj": self.cnpj or "",
            "segmento": self.segmento or "",
            "endereco": self.endereco or "",
            "telefone": self.telefone or "",
            "email": self.email or "",
            "site": self.site or "",
            "porte": self.porte or "",
            "numero_funcionarios": self.numero_funcionarios,
            "user_id": self.user_id,
            "user_name": self.user_name or "",
            "total_ganho": self.total_ganho,
            "total_perdido": self.total_perdido,
            "created_at": self.created_at.strftime("%d/%m/%Y") if self.created_at else ""
        }


class CrmOrigem(db.Model):
    """Origem / Canal de aquisição de oportunidades."""
    __tablename__ = "crm_origens"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    canal = db.Column(db.String(64), nullable=True)
    ativo = db.Column(db.Boolean, default=True)
    ordem = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "canal": self.canal or "",
            "ativo": self.ativo,
            "ordem": self.ordem,
            "created_at": self.created_at.strftime("%d/%m/%Y %H:%M") if self.created_at else ""
        }


class CrmContato(db.Model):
    """Contato de uma pessoa física vinculada à negociação ou empresa."""
    __tablename__ = "crm_contatos"

    id = db.Column(db.String(64), primary_key=True)
    empresa_id = db.Column(db.String(64), db.ForeignKey("crm_empresas.id", ondelete="SET NULL"), nullable=True, index=True)
    nome = db.Column(db.String(255), nullable=False, index=True)
    cargo = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    telefone = db.Column(db.String(64), nullable=True)
    celular = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    negociacoes = db.relationship("CrmNegociacao", backref="contato", lazy="dynamic")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "empresa_id": self.empresa_id,
            "empresa_nome": self.empresa.nome if self.empresa else "",
            "nome": self.nome,
            "cargo": self.cargo or "",
            "email": self.email or "",
            "telefone": self.telefone or "",
            "celular": self.celular or "",
            "whatsapp": self.celular or self.telefone or ""
        }


class CrmNegociacao(db.Model):
    """Oportunidade / Negociação comercial (Card do Kanban)."""
    __tablename__ = "crm_negociacoes"

    id = db.Column(db.String(64), primary_key=True)
    nome = db.Column(db.String(255), nullable=False, index=True)
    funil_id = db.Column(db.String(64), db.ForeignKey("crm_funis.id", ondelete="CASCADE"), nullable=False, index=True)
    etapa_id = db.Column(db.String(64), db.ForeignKey("crm_etapas.id", ondelete="RESTRICT"), nullable=False, index=True)
    empresa_id = db.Column(db.String(64), db.ForeignKey("crm_empresas.id", ondelete="SET NULL"), nullable=True, index=True)
    contato_id = db.Column(db.String(64), db.ForeignKey("crm_contatos.id", ondelete="SET NULL"), nullable=True, index=True)
    
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_name = db.Column(db.String(120), nullable=True)

    # Valores financeiros
    valor_unico = db.Column(db.Float, default=0.0, nullable=False)
    valor_mensal = db.Column(db.Float, default=0.0, nullable=False)
    valor_total = db.Column(db.Float, default=0.0, nullable=False)

    # Status: aberto, ganho, perdido, pausado
    status = db.Column(db.String(20), default="aberto", nullable=False, index=True)
    motivo_perda = db.Column(db.String(255), nullable=True)
    motivo_perda_id = db.Column(db.Integer, db.ForeignKey("crm_motivos_perda.id", ondelete="SET NULL"), nullable=True, index=True)
    motivo_perda_categoria = db.Column(db.String(64), nullable=True, index=True)
    data_estimada_fechamento = db.Column(db.Date, nullable=True, index=True)
    probabilidade = db.Column(db.Float, nullable=True)

    motivo_perda_rel = db.relationship("CrmMotivoPerda", foreign_keys=[motivo_perda_id])
    
    # Origem e Campanha
    origem = db.Column(db.String(120), nullable=True, index=True)      # Google Ads, Orgânico, etc.
    origem_id = db.Column(db.Integer, db.ForeignKey("crm_origens.id"), nullable=True)
    canal_origem = db.Column(db.String(64), nullable=True)
    temperatura = db.Column(db.String(20), nullable=True, index=True)
    canal_preferencial = db.Column(db.String(32), nullable=True)
    necessidade = db.Column(db.String(255), nullable=True)
    campanha = db.Column(db.String(120), nullable=True, index=True)    # TECHNOSOLLUS, SP, etc.
    filial = db.Column(db.String(64), nullable=True, index=True)       # RJ, SP, PR, ES, Santos

    origem_rel = db.relationship("CrmOrigem", backref=db.backref("negociacoes", lazy="dynamic"))

    # Qualificação Avançada & Relatórios (Feedback CRM)
    nivel_interesse = db.Column(db.String(32), nullable=True, index=True)     # baixo, medio, alto, urgente
    fonte_lead = db.Column(db.String(64), nullable=True, index=True)          # busca_paga, organico, redes_sociais, indicacao, outbound, whatsapp, eventos, outros
    localidade_lead = db.Column(db.String(120), nullable=True, index=True)   # Cidade/Região/Bairro do Lead

    # Pós-Venda & Satisfação do Cliente (CSAT / NPS)
    satisfacao_cliente = db.Column(db.Integer, nullable=True, index=True)     # 1 a 5 estrelas / nota
    pos_venda_obs = db.Column(db.Text, nullable=True)                         # Observações de atendimento do pós-venda
    pos_venda_preenchido_por = db.Column(db.String(120), nullable=True)       # Nome do operador do pós-venda
    pos_venda_em = db.Column(db.DateTime, nullable=True)                      # Data/hora do contato de pós-venda

    # Congelamento / Pausa da Negociação
    pausado_em = db.Column(db.DateTime, nullable=True)                        # Data/hora do congelamento
    pausado_motivo = db.Column(db.String(255), nullable=True)                 # Motivo da pausa da negociação

    # Próxima Tarefa agendada (cache para exibição rápida no card)
    proxima_tarefa_id = db.Column(db.String(64), nullable=True)
    proxima_tarefa_titulo = db.Column(db.String(255), nullable=True)
    proxima_tarefa_data = db.Column(db.DateTime, nullable=True, index=True)
    proxima_tarefa_tipo = db.Column(db.String(64), nullable=True)  # whatsapp, ligacao, reuniao, email

    # Régua comercial (1º contato, 2º contato, 3º contato)
    tentativas_contato = db.Column(db.Integer, default=0, nullable=False)
    ultimo_contato_em = db.Column(db.DateTime, nullable=True)

    # Vínculo com Propostas do Sollus Connected
    proposta_id = db.Column(db.Integer, nullable=True)
    
    # Vínculo com Pedidos do SollusFlow
    sollusflow_pedido_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)

    tarefas = db.relationship("CrmTarefa", backref="negociacao", cascade="all, delete-orphan", lazy="dynamic")
    interacoes = db.relationship("CrmInteracao", backref="negociacao", cascade="all, delete-orphan", lazy="dynamic")

    @property
    def tarefa_status(self) -> str:
        """Semáforo da tarefa: atrasada (red), hoje (yellow), no_prazo (green), sem_tarefa (none)."""
        if not self.proxima_tarefa_data:
            return "sem_tarefa"
        now = datetime.utcnow()
        if self.proxima_tarefa_data.date() < now.date():
            return "atrasada"
        elif self.proxima_tarefa_data.date() == now.date():
            return "hoje"
        return "no_prazo"

    @property
    def data_previsao_fechamento(self):
        return self.data_estimada_fechamento

    @data_previsao_fechamento.setter
    def data_previsao_fechamento(self, value):
        self.data_estimada_fechamento = value

    @property
    def categoria_perda(self) -> str | None:
        return self.motivo_perda_categoria

    @categoria_perda.setter
    def categoria_perda(self, value: str | None) -> None:
        self.motivo_perda_categoria = value

    @property
    def smart_empresa_nome(self) -> str:
        if self.empresa and self.empresa.nome:
            return self.empresa.nome.strip()
        if self.nome:
            if " - " in self.nome:
                parts = [p.strip() for p in self.nome.split(" - ") if p.strip()]
                if len(parts) >= 2:
                    if parts[-1].lower() in ("automatize", "manutencao", "manutencao", "suporte", "pos venda", "renovacao"):
                        return parts[0]
                    return parts[-1]
            return self.nome.strip()
        return "Sollus Comercial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "funil_id": self.funil_id,
            "etapa_id": self.etapa_id,
            "empresa_id": self.empresa_id,
            "empresa_nome": self.smart_empresa_nome,
            "contato_id": self.contato_id,
            "contato_nome": self.contato.nome if self.contato else "",
            "contato_whatsapp": self.contato.celular or self.contato.telefone if self.contato else "",
            "user_id": self.user_id,
            "user_name": self.user_name or "Não atribuído",
            "valor_unico": self.valor_unico,
            "valor_mensal": self.valor_mensal,
            "valor_total": self.valor_total,
            "status": self.status,
            "motivo_perda": self.motivo_perda or "",
            "motivo_perda_id": self.motivo_perda_id,
            "motivo_perda_categoria": self.motivo_perda_categoria or "",
            "categoria_perda": self.motivo_perda_categoria or "",
            "data_estimada_fechamento": self.data_estimada_fechamento.isoformat() if self.data_estimada_fechamento else "",
            "data_previsao_fechamento": self.data_estimada_fechamento.isoformat() if self.data_estimada_fechamento else "",
            "probabilidade": self.probabilidade,
            "origem": self.origem or "",
            "origem_id": self.origem_id,
            "canal_origem": self.canal_origem or "",
            "temperatura": self.temperatura or "",
            "canal_preferencial": self.canal_preferencial or "",
            "necessidade": self.necessidade or "",
            "campanha": self.campanha or "",
            "filial": self.filial or "",
            "nivel_interesse": self.nivel_interesse or "",
            "fonte_lead": self.fonte_lead or "",
            "localidade_lead": self.localidade_lead or "",
            "satisfacao_cliente": self.satisfacao_cliente,
            "pos_venda_obs": self.pos_venda_obs or "",
            "pos_venda_preenchido_por": self.pos_venda_preenchido_por or "",
            "pos_venda_em": self.pos_venda_em.strftime("%d/%m/%Y %H:%M") if self.pos_venda_em else "",
            "pausado_em": self.pausado_em.strftime("%d/%m/%Y %H:%M") if self.pausado_em else "",
            "pausado_motivo": self.pausado_motivo or "",
            "proxima_tarefa_titulo": self.proxima_tarefa_titulo or "",
            "proxima_tarefa_data": self.proxima_tarefa_data.strftime("%d/%m/%Y %H:%M") if self.proxima_tarefa_data else "",
            "proxima_tarefa_tipo": self.proxima_tarefa_tipo or "",
            "tarefa_status": self.tarefa_status,
            "proposta_id": self.proposta_id,
            "created_at": self.created_at.strftime("%d/%m/%Y") if self.created_at else ""
        }


class CrmTarefa(db.Model):
    """Tarefa agendada (Follow-up, WhatsApp, Ligação, Reunião)."""
    __tablename__ = "crm_tarefas"

    id = db.Column(db.String(64), primary_key=True)
    negociacao_id = db.Column(db.String(64), db.ForeignKey("crm_negociacoes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    titulo = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(64), default="whatsapp", nullable=False)  # whatsapp, ligacao, reuniao, visita, email
    data_vencimento = db.Column(db.DateTime, nullable=False, index=True)
    concluida = db.Column(db.Boolean, default=False, nullable=False, index=True)
    concluida_em = db.Column(db.DateTime, nullable=True)
    observacao = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "negociacao_id": self.negociacao_id,
            "user_id": self.user_id,
            "titulo": self.titulo,
            "tipo": self.tipo,
            "data_vencimento": self.data_vencimento.strftime("%d/%m/%Y %H:%M") if self.data_vencimento else "",
            "concluida": self.concluida,
            "observacao": self.observacao or ""
        }


class CrmInteracao(db.Model):
    """Linha do tempo (Timeline) com notas e histórico de alterações."""
    __tablename__ = "crm_interacoes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    negociacao_id = db.Column(db.String(64), db.ForeignKey("crm_negociacoes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name = db.Column(db.String(120), nullable=True)
    tipo = db.Column(db.String(32), default="anotacao", nullable=False)  # anotacao, whatsapp, ligacao, sistema, mudanca_etapa
    conteudo = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "negociacao_id": self.negociacao_id,
            "user_id": self.user_id,
            "user_name": self.user_name or "Sistema",
            "tipo": self.tipo,
            "conteudo": self.conteudo,
            "created_at": self.created_at.strftime("%d/%m/%Y às %H:%M") if self.created_at else ""
        }


class CrmLeadMarketing(db.Model):
    """Base rica de leads extraída do RD Station Marketing para prospecção ativa."""
    __tablename__ = "crm_leads_marketing"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    nome = db.Column(db.String(255), nullable=True)
    telefone = db.Column(db.String(64), nullable=True)
    celular = db.Column(db.String(64), nullable=True)
    empresa = db.Column(db.String(255), nullable=True, index=True)
    cargo = db.Column(db.String(120), nullable=True)
    cidade = db.Column(db.String(120), nullable=True)
    estado = db.Column(db.String(64), nullable=True)
    lead_scoring_perfil = db.Column(db.String(10), nullable=True)       # A, B, C, D
    lead_scoring_interesse = db.Column(db.Integer, default=0, nullable=False)
    origem_primeira = db.Column(db.String(255), nullable=True)
    origem_ultima = db.Column(db.String(255), nullable=True)
    evento_conversao = db.Column(db.String(255), nullable=True)
    data_conversao = db.Column(db.DateTime, nullable=True)
    tags = db.Column(db.Text, nullable=True)
    total_conversoes = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "nome": self.nome or "",
            "telefone": self.telefone or self.celular or "",
            "empresa": self.empresa or "",
            "cargo": self.cargo or "",
            "cidade": self.cidade or "",
            "estado": self.estado or "",
            "score_perfil": self.lead_scoring_perfil or "-",
            "score_interesse": self.lead_scoring_interesse,
            "origem": self.origem_primeira or "",
            "tags": [t.strip() for t in self.tags.split(",") if t.strip()] if self.tags else [],
            "total_conversoes": self.total_conversoes,
            "evento_conversao": self.evento_conversao or "",
        }


class CrmMotivoPerda(db.Model):
    """Motivo de perda cadastrado e categorizado para análise comercial."""
    __tablename__ = "crm_motivos_perda"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(64), nullable=False, default="outros", index=True)  # preco, concorrente, sem_contato, descarte, outros
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "categoria": self.categoria,
            "ativo": self.ativo,
            "ordem": self.ordem,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class CrmRegraAutomacao(db.Model):
    """Regra de automação de funil (gatilhos e tarefas automáticas)."""
    __tablename__ = "crm_regras_automacao"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    funil_id = db.Column(db.String(64), db.ForeignKey("crm_funis.id", ondelete="CASCADE"), nullable=True, index=True)
    etapa_id = db.Column(db.String(64), db.ForeignKey("crm_etapas.id", ondelete="CASCADE"), nullable=True, index=True)
    evento = db.Column(db.String(64), default="etapa_entrada", nullable=False, index=True)  # etapa_entrada, deal_criado
    acao_tipo = db.Column(db.String(64), default="criar_tarefa", nullable=False)  # criar_tarefa, distribuir_roleta
    tarefa_titulo = db.Column(db.String(255), nullable=True)
    tarefa_tipo = db.Column(db.String(64), default="whatsapp", nullable=False)  # whatsapp, ligacao, reuniao, email
    prazo_horas = db.Column(db.Integer, default=24, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def gatilho(self) -> str:
        return self.evento

    @property
    def acao(self) -> str:
        return self.acao_tipo

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "funil_id": self.funil_id,
            "etapa_id": self.etapa_id,
            "evento": self.evento,
            "acao_tipo": self.acao_tipo,
            "tarefa_titulo": self.tarefa_titulo or "",
            "tarefa_tipo": self.tarefa_tipo,
            "prazo_horas": self.prazo_horas,
            "ativo": self.ativo,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class CrmRoletaConsultor(db.Model):
    """Ponteiro e histórico da roleta comercial (distribuição round-robin)."""
    __tablename__ = "crm_roleta_consultores"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    consultor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    total_distribuido = db.Column(db.Integer, default=0, nullable=False)
    ultimo_recebimento = db.Column(db.DateTime, nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    consultor = db.relationship("User", foreign_keys=[consultor_id])

    @property
    def user_id(self) -> int:
        return self.consultor_id

    @property
    def ultimo_recebido_em(self) -> datetime | None:
        return self.ultimo_recebimento

    def __getitem__(self, item):
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def get(self, item, default=None):
        return getattr(self, item, default)

    def __contains__(self, item):
        return hasattr(self, item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "consultor_id": self.consultor_id,
            "consultor_nome": self.consultor.nome_completo if self.consultor else "",
            "total_distribuido": self.total_distribuido,
            "ultimo_recebimento": self.ultimo_recebimento.isoformat() if self.ultimo_recebimento else None,
            "ativo": self.ativo,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class CrmWebhook(db.Model):
    """Configuração de Webhook de Entrada ou Saída para o CRM."""
    __tablename__ = "crm_webhooks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(32), default="outbound", nullable=False)  # inbound | outbound
    url = db.Column(db.String(500), nullable=True)
    eventos = db.Column(db.String(255), nullable=True)  # deal_criado, etapa_alterada, deal_ganho, deal_perdido
    token_hash = db.Column(db.String(128), nullable=True, index=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    secret_key = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    logs = db.relationship("CrmWebhookLog", backref="webhook", cascade="all, delete-orphan", lazy="dynamic")

    @property
    def url_destino(self) -> str | None:
        return self.url

    @property
    def token_api(self) -> str | None:
        return self.token_hash

    @property
    def secret(self) -> str | None:
        return self.secret_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "tipo": self.tipo,
            "url": self.url or "",
            "eventos": self.eventos or "",
            "token_hash": self.token_hash or "",
            "ativo": self.ativo,
            "secret_key": self.secret_key or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class CrmWebhookLog(db.Model):
    """Log de auditoria e execução de disparos e recepção de webhooks."""
    __tablename__ = "crm_webhook_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    webhook_id = db.Column(db.Integer, db.ForeignKey("crm_webhooks.id", ondelete="CASCADE"), nullable=True, index=True)
    evento = db.Column(db.String(64), nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=True)
    request_payload = db.Column(db.Text, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    sucesso = db.Column(db.Boolean, default=False, nullable=False, index=True)
    tempo_ms = db.Column(db.Integer, default=0, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    @property
    def payload_enviado(self) -> str | None:
        return self.request_payload

    @property
    def response_status(self) -> int | None:
        return self.status_code

    @property
    def duracao_ms(self) -> int:
        return self.tempo_ms

    @property
    def created_at(self) -> datetime:
        return self.criado_em

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "evento": self.evento,
            "status_code": self.status_code,
            "sucesso": self.sucesso,
            "tempo_ms": self.tempo_ms,
            "request_payload": self.request_payload or "",
            "response_body": self.response_body or "",
            "criado_em": self.criado_em.isoformat() if self.criado_em else "",
        }


class CrmTemplateMensagem(db.Model):
    """Template rápido de mensagem comercial (WhatsApp/Email)."""
    __tablename__ = "crm_templates_mensagens"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(120), nullable=False)
    conteudo = db.Column(db.Text, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_por_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    criado_por = db.relationship("User", foreign_keys=[criado_por_id])

    @property
    def titulo(self) -> str:
        return self.nome

    @property
    def texto(self) -> str:
        return self.conteudo

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "conteudo": self.conteudo,
            "ativo": self.ativo,
            "criado_por_id": self.criado_por_id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class CrmRegraDistribuicao(db.Model):
    """Regra de roteamento regional de leads (Destino de Leads por Região / Estado / DDD / Filial)."""
    __tablename__ = "crm_regras_distribuicao"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(120), nullable=False)
    regiao = db.Column(db.String(64), nullable=False, index=True)  # SP, RJ, PR, ES, SANTOS, OUTROS
    estados = db.Column(db.String(255), nullable=True)             # Ex: "SP" ou "PR,SC,RS"
    ddds = db.Column(db.String(255), nullable=True)                # Ex: "11,12,13,14,15,16,17,18,19"
    consultor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0, nullable=False)
    observacao = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    consultor = db.relationship("User", foreign_keys=[consultor_id])

    def to_dict(self) -> dict[str, Any]:
        c_nome = ""
        if self.consultor:
            c_nome = self.consultor.nome_completo or self.consultor.usuario
        return {
            "id": self.id,
            "nome": self.nome,
            "regiao": self.regiao,
            "estados": self.estados or "",
            "ddds": self.ddds or "",
            "consultor_id": self.consultor_id,
            "consultor_nome": c_nome or f"Consultor #{self.consultor_id}",
            "ativo": self.ativo,
            "ordem": self.ordem,
            "observacao": self.observacao or "",
            "created_at": self.created_at.strftime("%d/%m/%Y %H:%M") if self.created_at else "",
            "updated_at": self.updated_at.strftime("%d/%m/%Y %H:%M") if self.updated_at else "",
        }


def _format_datetime_br(dt: datetime | None) -> str:
    """Converte datetime UTC para Horário de Brasília (UTC-3) e formata."""
    if not dt:
        return ""
    try:
        dt_local = dt - timedelta(hours=3)
        return dt_local.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return dt.strftime("%d/%m/%Y às %H:%M")


class CrmEquipamentoHistoricoPreco(db.Model):
    """Auditoria e histórico de alteração de preços de equipamentos (sincronizado com Estoque)."""
    __tablename__ = "crm_equipamentos_historico_preco"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipments.id", ondelete="CASCADE"), nullable=False, index=True)
    preco_antigo = db.Column(db.Float, nullable=False)
    preco_novo = db.Column(db.Float, nullable=False)
    alterado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    alterado_por = db.Column(db.String(120), nullable=True)
    origem = db.Column(db.String(64), default="crm_tabela_precos", nullable=False)  # crm_tabela_precos, estoque

    equipment = db.relationship("Equipment", backref=db.backref("historico_precos", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "equipment_id": self.equipment_id,
            "preco_antigo": self.preco_antigo,
            "preco_antigo_formatado": f"R$ {self.preco_antigo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "preco_novo": self.preco_novo,
            "preco_novo_formatado": f"R$ {self.preco_novo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "alterado_em": _format_datetime_br(self.alterado_em),
            "alterado_por": self.alterado_por or "Sistema",
            "origem": self.origem,
        }


class CrmSoftwareHistoricoPreco(db.Model):
    """Auditoria e histórico de alteração de preços de sistemas e softwares."""
    __tablename__ = "crm_software_historico_preco"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    software_plan_id = db.Column(db.Integer, db.ForeignKey("software_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    preco_antigo = db.Column(db.Float, nullable=False)
    preco_novo = db.Column(db.Float, nullable=False)
    alterado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    alterado_por = db.Column(db.String(120), nullable=True)
    origem = db.Column(db.String(64), default="crm_tabela_precos", nullable=False)

    software_plan = db.relationship("SoftwarePlan", backref=db.backref("historico_precos", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "software_plan_id": self.software_plan_id,
            "preco_antigo": self.preco_antigo,
            "preco_antigo_formatado": f"R$ {self.preco_antigo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "preco_novo": self.preco_novo,
            "preco_novo_formatado": f"R$ {self.preco_novo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "alterado_em": _format_datetime_br(self.alterado_em),
            "alterado_por": self.alterado_por or "Sistema",
            "origem": self.origem,
        }



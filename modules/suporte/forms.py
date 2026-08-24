"""Formulários utilizados nas telas de suporte."""
from __future__ import annotations

from datetime import datetime

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DateTimeLocalField,
    FileField,
    HiddenField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, Optional

STATUS_CHOICES = (
    ("entrada", "Entrada"),
    ("atencao", "Atenção"),
    ("concluido", "Concluído"),
    ("todos", "Todos"),
)


CHAMADO_STATUS_CHOICES = (
    ("ABERTO", "Aberto"),
    ("FECHADO", "Fechado"),
    ("OFICINA", "Oficina"),
)

CHAMADO_STATUS_FILTER_CHOICES = (("", "Todos"),) + CHAMADO_STATUS_CHOICES

CHAMADO_UNIDADE_CHOICES = (
    ("S", "Sollus Tecnologia"),
    ("T", "Technosollus"),
)

CHAMADO_NOVO_CLIENTE_CHOICES = (
    ("NAO", "Não"),
    ("SIM", "Sim"),
)


class AtendimentoFilterForm(FlaskForm):
    """Filtros aplicados sobre a lista de atendimentos."""

    class Meta:
        csrf = False

    status = SelectField("Status", choices=STATUS_CHOICES, default="entrada")
    usuario_designado = SelectField("Técnico", coerce=int, default=0)
    data_entrada = DateField("Data", validators=[Optional()])
    os_entrada = StringField("OS de Entrada", validators=[Optional()])
    empresa = StringField("Empresa", validators=[Optional()])

    def technician_id(self) -> int | None:
        value = self.usuario_designado.data or 0
        return value or None


STATUS_FIELD_CHOICES = [
    ("Entrada", "Entrada"),
    ("Atencao", "Atenção"),
    ("Concluido", "Concluído"),
]
class BaseAtendimentoForm(FlaskForm):
    cliente = StringField("Empresa", validators=[DataRequired(), Length(max=255)], filters=[lambda x: x.strip() if x else x])
    cnpj = StringField("CNPJ", validators=[Optional(), Length(max=18)], filters=[lambda x: x.strip() if x else x])
    email = StringField("E-mail", validators=[Optional(), Email(), Length(max=255)], filters=[lambda x: x.strip() if x else x])
    tipo_atendimento = SelectField("Tipo de atendimento", choices=[], validators=[DataRequired()], validate_choice=False)
    os_entrada = StringField("OS de entrada", validators=[DataRequired(), Length(max=64)], filters=[lambda x: x.strip() if x else x])
    os_saida = StringField("OS de saída", validators=[Optional(), Length(max=64)], filters=[lambda x: x.strip() if x else x])
    descricao = TextAreaField("Descrição", validators=[Optional()])
    observacoes = TextAreaField("Observações", validators=[Optional()])
    observacoes_alerta = TextAreaField("Observações de alerta", validators=[Optional()])
    sistema = SelectField("Sistema", choices=[], validators=[Optional()], validate_choice=False)
    quantidade_pessoas = StringField("Qtd. pessoas", validators=[Optional(), Length(max=32)], filters=[lambda x: x.strip() if x else x])
    texto_mobile = TextAreaField("Texto mobile", validators=[Optional()])
    status = SelectField("Status", choices=STATUS_FIELD_CHOICES, default="Entrada")
    data_entrada = DateTimeLocalField(
        "Data de entrada",
        format="%Y-%m-%dT%H:%M",
        default=datetime.utcnow,
        validators=[DataRequired()],
    )
    usuario_designado = SelectField("Técnico responsável", coerce=int, validators=[Optional()])
    arquivo_entrada = FileField("Arquivo de entrada", validators=[Optional()])


class NovoAtendimentoForm(BaseAtendimentoForm):
    class Meta:
        csrf = False  # Desabilitar CSRF para este formulário

    meet_start = DateTimeLocalField(
        "Data e hora da reuniao",
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
    )
    meet_link = HiddenField()
    meet_event_id = HiddenField()
    meet_extra_emails = TextAreaField(
        "E-mails adicionais",
        validators=[Optional(), Length(max=2000)],
    )
    meet_session_key = StringField(
        "Codigo sessao coletiva",
        validators=[Optional(), Length(max=64)],
    )


class EditarAtendimentoForm(BaseAtendimentoForm):
    class Meta:
        csrf = False  # Desabilitar CSRF para este formulário
    
    atendimento_id = HiddenField(validators=[DataRequired()])
    cliente = StringField("Empresa", validators=[Optional(), Length(max=255)], filters=[lambda x: x.strip() if x else x])
    tipo_atendimento = SelectField("Tipo de atendimento", choices=[], validators=[Optional()], validate_choice=False)
    os_entrada = StringField("OS de entrada", validators=[Optional(), Length(max=64)], filters=[lambda x: x.strip() if x else x])
    data_entrada = DateTimeLocalField(
        "Data de entrada",
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
    )
    data_atendimento = DateTimeLocalField(
        "Data de atendimento",
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
    )
    resumo_atendimento = TextAreaField("Resumo do atendimento", validators=[Optional()])
    arquivo_saida = FileField("Arquivo de saída", validators=[Optional()])


class ChamadoFiltroForm(FlaskForm):
    region = SelectField("Unidade", validators=[DataRequired()])
    data_visita = DateField("Data", validators=[Optional()])
    tecnico = SelectField("Técnico", choices=[], validators=[Optional()], validate_choice=False)
    status = SelectField("Status", choices=CHAMADO_STATUS_FILTER_CHOICES, default="")
    ordem_servico = StringField("Ordem de serviço", validators=[Optional(), Length(max=64)])


class CriarChamadoForm(FlaskForm):
    region = SelectField("Unidade", validators=[DataRequired()])
    unidade = SelectField(
        "Unidade",
        choices=CHAMADO_UNIDADE_CHOICES,
        validators=[Optional()],
        validate_choice=False,
    )
    novo_cliente = SelectField(
        "Novo cliente?",
        choices=CHAMADO_NOVO_CLIENTE_CHOICES,
        default="NAO",
        validators=[Optional()],
    )
    numero_proposta = StringField("Número da proposta", validators=[Optional(), Length(max=64)])
    data_os_criada = DateTimeLocalField(
        "Data e hora",
        validators=[DataRequired()],
        format="%Y-%m-%dT%H:%M",
        default=datetime.now,
    )
    cliente = StringField("Cliente", validators=[DataRequired(), Length(max=255)])
    contrato = SelectField("Contrato", choices=[], validators=[Optional()], validate_choice=False)
    cep = StringField("CEP", validators=[Optional(), Length(max=12)])
    bairro = StringField("Bairro", validators=[Optional(), Length(max=120)])
    ordem_servico = StringField("Ordem de serviço", validators=[DataRequired(), Length(max=64)])
    numero_manutencao = StringField("Número da manutenção", validators=[Optional(), Length(max=64)])
    tipo_atendimento = SelectField(
        "Tipo de atendimento",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    tecnico = SelectField(
        "Técnico",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    cnpj = StringField("CNPJ", validators=[Optional(), Length(max=18)])
    email_responsavel = StringField("E-mail", validators=[Optional(), Length(max=255)])
    arquivo_entrada = FileField("OS de entrada", validators=[Optional()])
    arquivo_saida = FileField("OS de saída", validators=[Optional()])


class EditarChamadoForm(FlaskForm):
    chamado_id = HiddenField(validators=[DataRequired()])
    region = SelectField("Unidade", validators=[Optional()], validate_choice=False)
    data = DateField("Data do atendimento", validators=[Optional()])
    cliente = StringField("Cliente", validators=[Optional(), Length(max=255)])
    cep = StringField("CEP", validators=[Optional(), Length(max=12)])
    bairro = StringField("Bairro", validators=[Optional(), Length(max=120)])
    ordem_servico = StringField("Ordem de serviço", validators=[Optional(), Length(max=64)])
    numero_manutencao = StringField("Número da manutenção", validators=[Optional(), Length(max=64)])
    tecnico = SelectField("Técnico", choices=[], validators=[Optional()], validate_choice=False)
    tipo_atendimento = SelectField(
        "Tipo de atendimento",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    cnpj = StringField("CNPJ", validators=[Optional(), Length(max=18)])
    email_responsavel = StringField("E-mail", validators=[Optional(), Length(max=255)])
    arquivo_entrada = FileField("OS de entrada", validators=[Optional()])
    arquivo_saida = FileField("OS de saída", validators=[Optional()])


class FecharChamadoForm(FlaskForm):
    data_atendimento = DateField("Data do atendimento", validators=[Optional()])
    hora_entrada = StringField("Hora de entrada", validators=[Optional(), Length(max=15)])
    hora_saida = StringField("Hora de saída", validators=[Optional(), Length(max=15)])
    arquivo_saida = FileField("OS de saída", validators=[Optional()])
    retorno = SelectField("Status", choices=CHAMADO_STATUS_CHOICES, default="FECHADO")
    tecnico = SelectField("Técnico", choices=[], validators=[Optional()], validate_choice=False)
    quem_atendeu = StringField("Responsável no local", validators=[Optional(), Length(max=120)])
    email_responsavel = StringField("E-mail", validators=[Optional(), Length(max=255)])
    descricao = TextAreaField("Descrição", validators=[Optional()])


class ConcluidoFilterForm(FlaskForm):
    usuario_designado = SelectField("Técnico", coerce=int, default=0)
    data_inicial = DateField("De", validators=[Optional()])
    data_final = DateField("Até", validators=[Optional()])

# Assistência técnica

ASSIST_STATUS_CHOICES = [
    ("Entrada", "Entrada"),
    ("em progresso", "Conserto interno"),
    ("aguardando", "Aguardando retorno/aprovação"),
    ("fabrica", "Envio fábrica"),
    ("concluído", "Retorno / testes finais"),
    ("devolucao_sem_reparo", "Devolucao sem reparo"),
    ("descarte", "Descarte"),
    ("retorno", "Retorno"),
]

ASSIST_TIPO_ENTRADA_CHOICES = [
    ("RETIRADO", "Retirado"),
    ("BALCAO", "Balcão"),
]

# Tipo de fluxo (guiado: Interno ou Fábrica)
ASSIST_TIPO_FLUXO_CHOICES = [
    ("interno", "Conserto interno"),
    ("fabrica", "Envio para fábrica"),
]


class AssistenciaFiltroForm(FlaskForm):
    class Meta:
        csrf = False

    # status = SelectField("Status", choices=[("", "Todos")] + ASSIST_STATUS_CHOICES, default="")
    status_group = StringField("Grupo de status", validators=[Optional(), Length(max=20)])
    unidade = SelectField("Unidade", choices=[], default="", validate_choice=False)
    departamento = SelectField("Departamento", choices=[], default="", validate_choice=False)
    os_codigo = StringField("OS", validators=[Optional(), Length(max=32)])
    cliente = StringField("Empresa", validators=[Optional(), Length(max=255)])
    orcamento_status = StringField("Status do orcamento", validators=[Optional(), Length(max=120)])
    fabrica_scope = StringField("Escopo fabrica", validators=[Optional(), Length(max=20)])
    contrato = SelectField(
        "Contrato",
        choices=[("", "Todos"), ("sim", "Com contrato"), ("nao", "Sem contrato")],
        default="",
    )
    tipo_entrada = SelectField("Tipo de entrada", choices=[("", "Todas")] + ASSIST_TIPO_ENTRADA_CHOICES, default="")
    data_inicial = DateField("De", validators=[Optional()])
    data_final = DateField("Até", validators=[Optional()])


class AssistenciaTarefaForm(FlaskForm):
    class Meta:
        csrf = False

    nome = StringField("Empresa", validators=[DataRequired(), Length(max=255)])
    cnpj = StringField("CNPJ", validators=[Optional(), Length(max=20)])
    unidade = SelectField("Unidade", choices=[], validators=[DataRequired()], validate_choice=False)
    departamento_responsavel = SelectField(
        "Departamento responsável",
        choices=[],
        validators=[DataRequired()],
        validate_choice=False,
    )
    usuario_designado = SelectField("Técnico designado", choices=[], validators=[Optional()], validate_choice=False)
    tipo_entrada = SelectField("Tipo de entrada", choices=ASSIST_TIPO_ENTRADA_CHOICES, validators=[DataRequired()])
    tipo_atendimento = SelectField("Tipo de atendimento", choices=[], validators=[Optional()], validate_choice=False)
    cep = StringField("CEP", validators=[Optional(), Length(max=12)])
    bairro = StringField("Bairro", validators=[Optional(), Length(max=120)])
    contrato = SelectField(
        "Contrato",
        choices=[("sim", "Sim"), ("nao", "Não")],
        validators=[DataRequired()],
    )
    orcamento = StringField("Orçamento", validators=[Optional(), Length(max=500)])
    fluxo_tipo = SelectField(
        "Fluxo",
        choices=ASSIST_TIPO_FLUXO_CHOICES,
        default="interno",
        validators=[DataRequired()],
    )
    os_codigo = StringField("OS", validators=[DataRequired(), Length(max=100)])
    data_criacao = DateField("Data de entrada", validators=[DataRequired()])
    data_fim = DateField("Data limite", validators=[DataRequired()])
    status = SelectField("Status", choices=ASSIST_STATUS_CHOICES, default="Entrada")
    descricao = TextAreaField("Descrição", validators=[Optional()])
    notificacao = SelectField(
        "Notificação",
        choices=[("sim", "Sim"), ("nao", "Não")],
        default="nao",
    )
    arquivo = FileField("Anexo", validators=[Optional()])


class EditarAssistenciaTarefaForm(AssistenciaTarefaForm):
    status = SelectField("Status", choices=ASSIST_STATUS_CHOICES, default="Entrada", validate_choice=False)
    notificacao = SelectField(
        "Notificação",
        choices=[("sim", "Sim"), ("nao", "Não"), ("devolucao", "Devolução")],
        default="nao",
        validate_choice=False,
    )
    orcamento = StringField("Orçamento", validators=[Optional(), Length(max=500)])
    fluxo_tipo = SelectField(
        "Fluxo",
        choices=ASSIST_TIPO_FLUXO_CHOICES,
        validators=[Optional()],
        validate_choice=False,
    )
    tipo_entrada = SelectField(
        "Tipo de entrada",
        choices=ASSIST_TIPO_ENTRADA_CHOICES,
        validators=[Optional()],
        validate_choice=False,
    )
    tipo_atendimento = SelectField("Tipo de atendimento", choices=[], validators=[Optional()], validate_choice=False)
    contrato = SelectField(
        "Contrato",
        choices=[("sim", "Sim"), ("nao", "Não")],
        validators=[Optional()],
        validate_choice=False,
    )
    # Sobrescreve para tornar opcional no form de edição (o modal pode não ter esses valores preenchidos)
    data_criacao = DateField("Data de entrada", validators=[Optional()])
    data_fim = DateField("Data limite", validators=[Optional()])
    os_codigo = StringField("OS", validators=[Optional(), Length(max=100)])
    nome = StringField("Empresa", validators=[Optional(), Length(max=255)])
    unidade = SelectField("Unidade", choices=[], validators=[Optional()], validate_choice=False)
    departamento_responsavel = SelectField(
        "Departamento responsável",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    tarefa_id = HiddenField(validators=[DataRequired()])
    atualizar_tarefa = TextAreaField("Atualizar Tarefa", validators=[Optional(), Length(max=5000)])



class AssistenciaEnvioForm(FlaskForm):
    class Meta:
        csrf = False

    tarefa_id = HiddenField(validators=[DataRequired()])
    acao_fabrica = SelectField(
        "Acao",
        choices=[("envio", "Registrar envio"), ("retorno", "Registrar retorno")],
        default="envio",
        validators=[Optional()],
    )
    data_evento = DateField("Data", validators=[Optional()])
    data_envio = DateField("Data de envio", validators=[Optional()])
    data_retorno = DateField("Retorno previsto", validators=[Optional()])
    status = SelectField("Status", choices=[("fabrica", "Fábrica"), ("aguardando", "Aguardando")], default="fabrica")
    orcamento = StringField("Orçamento", validators=[Optional(), Length(max=50)])

    obs = TextAreaField("Observacoes", validators=[Optional(), Length(max=5000)])


class AssistenciaRespostaForm(FlaskForm):
    class Meta:
        csrf = False

    tarefa_id = HiddenField(validators=[DataRequired()])
    arquivo_resposta = FileField("Resposta/retorno", validators=[DataRequired()])

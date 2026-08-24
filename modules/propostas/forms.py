from flask_wtf import FlaskForm

from wtforms import (
    StringField, PasswordField, SelectField, SelectMultipleField,
    TextAreaField, SubmitField, IntegerField, BooleanField, RadioField, HiddenField
)
from wtforms.validators import (

    DataRequired, NumberRange, Email, ValidationError, Optional, Length, Regexp

)

from flask_wtf.file import FileField, FileAllowed, FileRequired

from modules.propostas.models import ParamCategory, ServicoType, ModalidadeType, PERMISSION_DEFINITIONS
from modules.propostas.constants import ISSUER_COMPANY_CHOICES, DEFAULT_ISSUER_CODE


# =========================

#  Validador e Funcao de CNPJ

# =========================



def cnpj_valido(cnpj):

    """Valida se um CNPJ é válido."""

    # Remove caracteres não numéricos

    cnpj = ''.join(filter(str.isdigit, cnpj or ''))

    if len(cnpj) != 14:

        return False

    # CNPJs com todos os dígitos iguais são inválidos

    if cnpj == cnpj[0] * 14:

        return False



    def calc_digit(cnpj_slice, multipliers):

        total = sum(int(d) * m for d, m in zip(cnpj_slice, multipliers))

        remainder = total % 11

        return '0' if remainder < 2 else str(11 - remainder)



    # Primeiro digito verificador

    mult1 = [5,4,3,2,9,8,7,6,5,4,3,2]

    d1 = calc_digit(cnpj[:12], mult1)

    # Segundo digito verificador

    mult2 = [6] + mult1

    d2 = calc_digit(cnpj[:12] + d1, mult2)



    return cnpj[-2:] == d1 + d2





def validar_cnpj(form, field):

    """WTForms validator para campo CNPJ."""

    if not cnpj_valido(field.data):

        raise ValidationError("CNPJ inválido.")



# =========================

#  Equipamentos Form

# =========================

class EquipmentForm(FlaskForm):

    name = StringField(

        'Nome',

        validators=[DataRequired(message='Informe o nome do equipamento.')],

        render_kw={'required': True}

    )

    description = TextAreaField(

        'Descrição',

        validators=[DataRequired(message='Descreva o equipamento.')],

        render_kw={'required': True, 'rows': 3}

    )

    unit_price = StringField(

        'Preço unitário',
        validators=[DataRequired(message='Informe o preço unitário.')],

        render_kw={'required': True}

    )

    quantity = StringField(

        'Quantidade',

        validators=[

            DataRequired(message='Informe a quantidade disponível.'),

            Regexp(r'^\d+$', message='Use apenas números inteiros.'),

        ],

        render_kw={'required': True, 'inputmode': 'numeric'}

    )

    illustration = FileField(

        'Imagem',

        validators=[

            FileRequired(message='Envie uma imagem do equipamento.'),

            FileAllowed(['jpg', 'png', 'jpeg'], 'Apenas imagens são permitidas'),

        ]

    )

    submit = SubmitField('Salvar equipamento')


# =========================
#  Peças Form
# =========================
class PartForm(FlaskForm):
    name = StringField(
        'Nome',
        validators=[DataRequired(message='Informe o nome da peça.')],
        render_kw={'required': True}
    )
    description = TextAreaField(
        'Descrição',
        validators=[Optional()],
        render_kw={'rows': 3}
    )
    unit_price = StringField(
        'Preço unitário',
        validators=[DataRequired(message='Informe o preço unitário.')],
        render_kw={'required': True}
    )
    quantity = StringField(
        'Quantidade',
        validators=[
            DataRequired(message='Informe a quantidade disponível.'),
            Regexp(r'^\d+$', message='Use apenas números inteiros.'),
        ],
        render_kw={'required': True, 'inputmode': 'numeric'}
    )
    illustration = FileField(
        'Imagem',
        validators=[
            Optional(),
            FileAllowed(['jpg', 'png', 'jpeg'], 'Apenas imagens são permitidas'),
        ]
    )
    submit = SubmitField('Salvar peça')


# =========================

#  Proposals Form

# =========================

def cpf_valido(cpf: str) -> bool:

    digits = ''.join(filter(str.isdigit, cpf or ''))

    if len(digits) != 11:

        return False

    if digits == digits[0] * 11:

        return False



    def calc_digit(digs: str, factor: int) -> str:

        total = sum(int(d) * (factor - idx) for idx, d in enumerate(digs))

        remainder = total % 11

        return '0' if remainder < 2 else str(11 - remainder)



    d1 = calc_digit(digits[:9], 10)

    d2 = calc_digit(digits[:9] + d1, 11)

    return digits[-2:] == d1 + d2





class ProposalForm(FlaskForm):

    document_type  = RadioField(

        'Tipo de documento',

        choices=[('cnpj', 'CNPJ'), ('cpf', 'CPF')],

        default='cnpj',

        validators=[Optional()],

    )

    company        = StringField('Empresa', validators=[Optional()])

    document       = StringField('Documento do Cliente', validators=[Optional()])

    client_name    = StringField('Pessoa de Contato', validators=[Optional()])

    email          = StringField('E-mail', validators=[Optional(), Email(message="E-mail inválido")])

    telefone       = StringField('Telefone', validators=[Optional()])

    issuer_company_code = SelectField('Filial', choices=ISSUER_COMPANY_CHOICES, default=DEFAULT_ISSUER_CODE, validators=[Optional()])



    # Parametros dinamicamente preenchidos

    pagto_equip    = SelectField('Condições de Pagamento (Equipamento)', coerce=str)

    prazo_entrega  = SelectField('Prazo de Entrega', coerce=str)

    frete          = SelectField('Frete', coerce=str)

    validade       = StringField('Validade da Proposta', validators=[Optional()])

    garantia_eq    = SelectField('Garantia de Equipamento', coerce=str)

    garantia_sys   = SelectField('Garantia de Sistema', coerce=str)

    observacao_comercial = TextAreaField('Observação complementar (particularidades)', validators=[Optional()])
    ambiente_incluir = BooleanField('Incluir fotos do ambiente do cliente?')



    # Campos Outros

    pagto_equip_other   = StringField()

    prazo_entrega_other = StringField()

    frete_other         = StringField()


    garantia_eq_other   = StringField()

    garantia_sys_other  = StringField()



    equipments = SelectMultipleField('Equipamentos', coerce=int)

    usar_sistema = BooleanField('Adicionar Sistema de Ponto ou Acesso?')

    sistema_opcao = SelectField('Sistema', coerce=str, validate_choice=False)

    sistema_quantidade = IntegerField('Quantidade de Pessoas', validators=[Optional(), NumberRange(min=1)], default=1)

    sistema_preco_unitario = StringField('Valor mensal', validators=[Optional()])
    sistema_preco_manual = BooleanField('Valor Fixo / Plano?', default=True)
    locacao_vigencia = StringField('Vigência da locação', validators=[Optional()])
    locacao_modelo = SelectField(
        'Modelo da locação',
        choices=[
            ('sintetico', 'Sintético (simplificado)'),
            ('analitico', 'Analítico (detalhado)'),
        ],
        default='sintetico',
        validators=[Optional()],
    )
    locacao_qtd_cnpjs = IntegerField('Qtd. CNPJs', validators=[Optional(), NumberRange(min=1)])
    locacao_qtd_equipamentos = IntegerField('Qtd. equipamentos', validators=[Optional(), NumberRange(min=1)])



    # Proposta em nome de outro usuario

    usar_outro_usuario = SelectField(

        'Fazer proposta em nome de outro consultor?',

        choices=[('nao', 'Não'), ('sim', 'Sim')],

        default='nao',

        validators=[Optional()]

    )

    outro_usuario = SelectField('Selecione o Consultor', coerce=int, validate_choice=False)



    # Tipo de Servico

    servico_type = SelectField(

        'Tipo de Serviço',

        choices=[(st.name, st.label) for st in ServicoType],

        validators=[Optional()],

        coerce=lambda v: ServicoType[v]

    )

    rep_categoria_programa = BooleanField('Equipamento \u00e9 REP-P (Programa)?')
    rep_tem_mobile = BooleanField('Tem mobile?')
    rep_qtd_mobile = IntegerField('Quantidade de mobiles', validators=[Optional(), NumberRange(min=1)])
    rep_mobile_valor_mensal = StringField(
        'Acréscimo mensal dos mobiles',
        validators=[Optional()],
    )

    # Modalidade

    modalidade_type = SelectField(

        'Modalidade',

        choices=[(mt.name, mt.label) for mt in ModalidadeType],

        validators=[Optional()],

        coerce=lambda v: ModalidadeType[v]

    )



    enviar_email = BooleanField('Enviar e-mail para o cliente?')

    email_corpo = TextAreaField('Conteúdo do e-mail', validators=[Optional()])

    enviar_copia = BooleanField('Copiar outros e-mails?')

    email_cc = TextAreaField('E-mails em cópia', validators=[Optional()])



    submit         = SubmitField('Gerar Proposta')



# =========================

#  Usuários Form

# =========================

class UserForm(FlaskForm):
    usuario       = StringField('Usuário', validators=[DataRequired()])
    nome_completo = StringField('Nome Completo', validators=[DataRequired()])
    email         = StringField('E-mail', validators=[DataRequired(message="O e-mail é obrigatório."), Email(message="E-mail inválido")])
    phone         = StringField('Telefone', validators=[Optional(), Length(max=32)])
    department_ids = SelectMultipleField('Departamentos', coerce=int, validate_choice=False)
    unit_code     = SelectField('Empresa', choices=ISSUER_COMPANY_CHOICES, validators=[DataRequired()], validate_choice=False)
    ramal         = StringField('Ramal', validators=[Optional(), Length(max=32)])
    senha         = PasswordField('Senha', validators=[DataRequired()])
    tipo          = SelectField('Tipo', choices=[], coerce=str, validators=[DataRequired()])
    prox_num      = IntegerField('Próximo Nº de Proposta', default=1, validators=[NumberRange(min=1)])
    is_active     = BooleanField('Usuário ativo?', default=True)
    submit        = SubmitField('Cadastrar Usuário')


class PermissionFlagsMixin:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for key, meta in PERMISSION_DEFINITIONS.items():
            if hasattr(cls, key):
                continue
            setattr(
                cls,
                key,
                BooleanField(
                    meta['label'],
                    default=bool(meta.get('default', False)),
                ),
            )


class DepartmentPermissionBaseForm(PermissionFlagsMixin, FlaskForm):
    name = StringField('Nome do departamento', validators=[DataRequired(), Length(max=120)])


class DepartmentCreateForm(DepartmentPermissionBaseForm):
    submit = SubmitField('Adicionar departamento')


class DepartmentUpdateForm(DepartmentPermissionBaseForm):
    department_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField('Salvar alterações')


class RolePermissionBaseForm(PermissionFlagsMixin, FlaskForm):

    label = StringField('Nome', validators=[DataRequired(), Length(max=120)])

class RolePermissionCreateForm(RolePermissionBaseForm):

    name   = StringField('Identificador', validators=[DataRequired(), Length(max=50), Regexp(r'^[a-z0-9_]+$', message='Use apenas letras minúsculas, números e underline.')])

    submit = SubmitField('Criar tipo')





class RolePermissionUpdateForm(RolePermissionBaseForm):

    role_id = HiddenField(validators=[DataRequired()])

    submit  = SubmitField('Salvar alterações')





# =========================

#  Parametros da Proposta

# =========================

class ParamOptionForm(FlaskForm):

    category = SelectField(

        'Categoria',

        choices=[(c.name, c.name.replace('_', ' ').title()) for c in ParamCategory],

        coerce=lambda v: ParamCategory[v]

    )

    label    = StringField('Valor', validators=[DataRequired()])

    submit   = SubmitField('Salvar')





class SystemOptionOverrideForm(FlaskForm):

    description = TextAreaField('Descrição', validators=[Optional()])

    image = FileField(

        'Imagem',

        validators=[FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Apenas imagens são permitidas')]

    )

    remove_image = BooleanField('Remover imagem personalizada?')

    submit = SubmitField('Salvar alterações')


class SystemOptionCreateForm(FlaskForm):

    label = StringField('Nome do sistema', validators=[DataRequired()])

    key = StringField('Chave (opcional)', validators=[Optional()])

    description = TextAreaField('Descrição', validators=[Optional()])

    image = FileField(
        'Imagem',
        validators=[FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Apenas imagens são permitidas')]
    )

    submit = SubmitField('Adicionar sistema')













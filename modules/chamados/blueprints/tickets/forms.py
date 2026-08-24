from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField, DateField
from wtforms.validators import DataRequired, Length, Optional
from flask_wtf.file import FileField, FileAllowed

ALLOWED_EXT = ('pdf','png','jpg','jpeg','txt','log','zip','doc','docx','xls','xlsx')

class TicketForm(FlaskForm):
    title = StringField('Título', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Descrição', validators=[DataRequired()])
    priority = SelectField('Prioridade', choices=[
        ('low', 'Baixa'), ('medium', 'Média'), ('high', 'Alta'), ('urgent', 'Urgente')
    ], default='medium')
    submit = SubmitField('Salvar')

class CommentForm(FlaskForm):
    body = TextAreaField('Comentário', validators=[DataRequired()])
    submit = SubmitField('Enviar')

class TicketEditForm(FlaskForm):
    status = SelectField('Status', choices=[
        ('open', 'Aberto'),
        ('in_progress', 'Em andamento'),
        ('resolved', 'Resolvido'),
        ('closed', 'Fechado'),
    ])
    priority = SelectField('Prioridade', choices=[
        ('low', 'Baixa'), ('medium', 'Média'), ('high', 'Alta'), ('urgent', 'Urgente')
    ])
    submit = SubmitField('Atualizar')

class AttachmentForm(FlaskForm):
    file = FileField('Anexo', validators=[FileAllowed(ALLOWED_EXT, 'Extensão não permitida.')])
    submit = SubmitField('Enviar')

class FilterForm(FlaskForm):
    status = SelectField('Status', choices=[('', 'Todos'), ('open','Aberto'),('in_progress','Em andamento'),('resolved','Resolvido'),('closed','Fechado')], default='')
    priority = SelectField('Prioridade', choices=[('', 'Todas'), ('low','Baixa'),('medium','Média'),('high','Alta'),('urgent','Urgente')], default='')
    assignee_id = SelectField('Responsável', coerce=int, default=0)
    date_from = DateField('De', validators=[Optional()])
    date_to = DateField('Até', validators=[Optional()])
    submit = SubmitField('Filtrar')

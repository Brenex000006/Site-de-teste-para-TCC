from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email
from flask_wtf.file import FileField, FileAllowed

class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    submit = SubmitField("Entrar")

class UsuarioForm(FlaskForm):
    nome = StringField("Nome", validators=[DataRequired()])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    senha = PasswordField("Senha", validators=[DataRequired()])
    tipo = SelectField("Tipo", choices=[("admin", "Admin"), ("comum", "Comum")], validators=[DataRequired()])
    endereco_imagem = FileField("Imagem", validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField("Salvar")

class EditarForm(FlaskForm):
    nome = StringField("Nome", validators=[DataRequired()])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    endereco_imagem = FileField("Nova imagem (opcional)", validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField("Salvar Alterações")

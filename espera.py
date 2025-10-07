import os
import threading
import uuid
import io
import mysql.connector
import pyotp
import qrcode
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Flask-WTF e CSRF
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.csrf import generate_csrf
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired

from registrar_mudancas import carregar_buffer, debounce_worker, registrar_alteracao_buffer
from utils import pegar_config

# Configuração
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Habilita CSRF
csrf = CSRFProtect(app)

@app.context_processor
def inject_csrf_token():
    """Permite usar {{ csrf_token() }} em formulários que não usam FlaskForm"""
    return dict(csrf_token=generate_csrf)

# Banco de dados MySQL
db = mysql.connector.connect(
    host="127.0.0.1",
    user="Root",
    password="root",
    database="tcc_reconhece"
)

# Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class Admin(UserMixin):
    id = 1

@login_manager.user_loader
def load_user(user_id):
    if user_id == "1":
        return Admin()
    return None

# --- Flask-WTF Formulários ---
class LoginForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired()])
    password = PasswordField("Senha", validators=[DataRequired()])


# --- Funções auxiliares ---
def update_env_variable(key, value, env_path='.env'):
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()

    with open(env_path, 'w') as f:
        found = False
        for line in lines:
            if line.startswith(f"{key}="):
                f.write(f"{key}={value}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"{key}={value}\n")

    load_dotenv(env_path, override=True)

def get_or_create_admin_2fa_secret():
    """Retorna a chave secreta do admin ou cria uma nova"""
    secret = os.getenv('ADMIN_2FA_SECRET')
    if not secret:
        secret = pyotp.random_base32()
        update_env_variable('ADMIN_2FA_SECRET', secret)
    return secret

# --- Funções de banco de dados ---
def salvar_usuario(email, nome, imagem_url):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (email, nome, endereco_imagem) VALUES (%s, %s, %s)",
            (email, nome, imagem_url)
        )
        db.commit()
        return True
    except mysql.connector.errors.IntegrityError as e:
        print("Erro ao inserir email:", e)
        return False
    finally:
        cursor.close()

def carregar_usuarios():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()
    cursor.close()
    return usuarios

def atualizar_usuario(email_antigo, email_novo, nome, imagem_url=None):
    cursor = db.cursor()
    if imagem_url:
        sql = "UPDATE usuarios SET email = %s, nome = %s, endereco_imagem = %s WHERE email = %s"
        vals = (email_novo, nome, imagem_url, email_antigo)
    else:
        sql = "UPDATE usuarios SET email = %s, nome = %s WHERE email = %s"
        vals = (email_novo, nome, email_antigo)
    cursor.execute(sql, vals)
    db.commit()

def excluir_usuario(email):
    cursor = db.cursor()
    cursor.execute("DELETE FROM usuarios WHERE email = %s", (email,))
    db.commit()

# --- Rotas ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    secret = os.getenv('ADMIN_2FA_SECRET')
    bypass = True  # só para testes

    if form.validate_on_submit():
        usuario = form.username.data
        senha = form.password.data

        if usuario == os.getenv("ADMIN_USERNAME") and senha == os.getenv("ADMIN_PASSWORD"):
            if bypass:
                login_user(Admin())
                return redirect(url_for('lista'))

            if not secret:
                login_user(Admin())
                flash("Configure o 2FA antes de continuar.", "info")
                return redirect(url_for('two_factor_setup'))
            else:
                codigo_2fa = request.form.get('codigo_2fa')
                totp = pyotp.TOTP(secret)
                if totp.verify(codigo_2fa, valid_window=1):
                    login_user(Admin())
                    return redirect(url_for('lista'))
                else:
                    flash("Código 2FA inválido.", "danger")
        else:
            flash("Credenciais inválidas.", "danger")

    return render_template('login.html', form=form, secret=secret)

# --- NOVA ROTA: Esqueci Senha ---
@app.route('/esqueci_senha', methods=['GET', 'POST'])
def esqueci_senha():
    if request.method == 'POST':
        email = request.form.get('email')

        # MOCK por enquanto
        if email == os.getenv("ADMIN_EMAIL"):
            flash("Um link de recuperação foi enviado para seu email.", "info")
            # Futuramente: gerar token, salvar no banco e enviar por e-mail
            return redirect(url_for('login'))
        else:
            flash("Email não encontrado.", "danger")

    return render_template('esqueci_senha.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/cadastrar', methods=['GET', 'POST'])
@login_required
def cadastrar():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        imagem = request.files['imagem']
        usuarios = carregar_usuarios()
        if any(u['email'] == email for u in usuarios):
            flash("Email já cadastrado.")
            return redirect(url_for('cadastrar'))

        if imagem:
            nome_arquivo = secure_filename(imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            imagem.save(caminho_arquivo)
            url_imagem = url_for('static', filename=f'uploads/{nome_unico}')
            URL_ABSO = os.path.abspath(caminho_arquivo)

            if salvar_usuario(email, nome, URL_ABSO):
                flash("Pessoa cadastrada com sucesso!")
                registrar_alteracao_buffer("usuarios", "adicionar", nome)
                registrar_alteracao_buffer("imagens", "adicionar", url_imagem)
            else:
                flash("Erro ao cadastrar pessoa.")
            return redirect(url_for('cadastrar'))

    return render_template('cadastrar.html')

@app.route('/lista', methods=['GET'])
@login_required
def lista():
    filtro = request.args.get('filtro', '')
    data = request.args.get('data', '')

    cursor = db.cursor(dictionary=True)
    query = "SELECT * FROM usuarios WHERE 1=1"
    valores = []

    if filtro:
        query += " AND (nome LIKE %s OR email LIKE %s)"
        filtro_valor = f"%{filtro}%"
        valores.extend([filtro_valor, filtro_valor])

    if data:
        query += " AND DATE(criado_em) = %s"
        valores.append(data)

    cursor.execute(query, valores)
    pessoas = cursor.fetchall()
    pessoas = imagem_corrigida(pessoas)
    cursor.close()

    return render_template('lista.html', pessoas=pessoas, filtro=filtro, data=data)

def imagem_corrigida(pessoas):
    for pessoa in pessoas:
        pessoa['endereco_imagem'] = "/static/" + str(pessoa['endereco_imagem'].replace("\\", "/").split("/static/")[1])
    return pessoas

@app.route('/editar/<email>', methods=['GET', 'POST'])
@login_required
def editar(email):
    usuarios = carregar_usuarios()
    usuarios = imagem_corrigida(usuarios)
    pessoa = next((u for u in usuarios if u['email'] == email), None)
    if not pessoa:
        flash("Pessoa não encontrada.")
        return redirect(url_for('lista'))

    if request.method == 'POST':
        nome = request.form['nome']
        novo_email = request.form['novo_email']
        nova_imagem = request.files.get('imagem')

        if nova_imagem and nova_imagem.filename:
            imagem_antiga = pessoa['endereco_imagem'].replace('/static/', '')
            caminho_antigo = os.path.join('static', imagem_antiga)
            if os.path.exists(caminho_antigo):
                os.remove(caminho_antigo)

            nome_arquivo = secure_filename(nova_imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            nova_imagem.save(caminho_arquivo)
            Url_Abs = os.path.abspath(caminho_arquivo)
            registrar_alteracao_buffer("usuarios", "deletar", nome)
            registrar_alteracao_buffer("imagens", "deletar", nome_unico)
        else:
            relative_path = pessoa['endereco_imagem'].lstrip('/')
            base_dir = os.path.dirname(os.path.abspath(__file__))
            Url_Abs = os.path.abspath(os.path.join(base_dir, relative_path))

        atualizar_usuario(email, novo_email, nome, Url_Abs)
        flash("Cadastro atualizado com sucesso!")
        return redirect(url_for('lista'))

    return render_template('editar.html', pessoa=pessoa)

@app.route('/excluir/<email>', methods=['POST'])
@login_required
def excluir(email):
    usuarios = carregar_usuarios()
    pessoa = next((u for u in usuarios if u['email'] == email), None)
    if pessoa:
        imagem_url = pessoa.get('endereco_imagem', '').replace('/static/', '')
        caminho = os.path.join('static', imagem_url)
        if os.path.exists(caminho):
            registrar_alteracao_buffer("usuarios", "deletar", email)
            registrar_alteracao_buffer("imagens", "deletar", imagem_url)
            os.remove(caminho)
    excluir_usuario(email)
    flash("Registro excluído com sucesso!")
    return redirect(url_for('lista'))

@app.route('/2fa_qr')
def two_factor_qr():
    secret = os.getenv('ADMIN_2FA_SECRET')
    if not secret:
        img = qrcode.make("2FA não configurado")
    else:
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name="Admin TCC", issuer_name="Site TCC Facial")
        img = qrcode.make(uri)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/2fa_setup', methods=['GET', 'POST'])
@login_required
def two_factor_setup():
    secret = get_or_create_admin_2fa_secret()

    if request.method == 'POST':
        codigo = request.form['codigo_2fa']
        totp = pyotp.TOTP(secret)
        if totp.verify(codigo, valid_window=1):
            flash("2FA configurado com sucesso! Faça login novamente.")
            logout_user()
            return redirect(url_for('login'))
        else:
            flash("Código 2FA inválido. Tente novamente.")

    provisioning_url = pyotp.TOTP(secret).provisioning_uri(
        name="admin",
        issuer_name="Sistema de Cadastro Facial"
    )
    return render_template('2fa_setup.html', provisioning_url=provisioning_url)

# --- Inicia a aplicação ---
if __name__ == '__main__':
    lbd_url = pegar_config("LBD")
    print(lbd_url)
    if lbd_url:
        carregar_buffer()
        threading.Thread(target=debounce_worker, daemon=True).start()
        app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        print("[ERROR] Não foi possível pegar config da Lambda, o programa não será iniciado!")

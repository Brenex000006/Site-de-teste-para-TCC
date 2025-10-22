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
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email
from flask_wtf.file import FileField, FileAllowed

# módulos do seu projeto
from registrar_mudancas import carregar_buffer, debounce_worker, registrar_alteracao_buffer
from utils import pegar_config, enviar_backup_s3

# ---------------- CONFIGURAÇÃO ----------------
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or 'dev-secret'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Habilita CSRF
csrf = CSRFProtect(app)


@app.context_processor
def inject_csrf_token():
    """Permite usar {{ csrf_token() }} em formulários sem FlaskForm"""
    return dict(csrf_token=generate_csrf)

# ---------------- FUNÇÕES AUXILIARES ----------------
def update_env_variable(key, value, env_path='.env'):
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    found = False
    with open(env_path, 'w', encoding='utf-8') as f:
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
    secret = os.getenv('ADMIN_2FA_SECRET')
    if not secret:
        secret = pyotp.random_base32()
        update_env_variable('ADMIN_2FA_SECRET', secret)
    return secret

# ---------------- BANCO DE DADOS ----------------
db = mysql.connector.connect(
    host=os.getenv('DB_HOST', "127.0.0.1"),
    user=os.getenv('DB_USER', "Root"),
    password=os.getenv('DB_PASSWORD', "root"),
    database=os.getenv('DB_NAME', "tcc_reconhece")
)

def ensure_db_connected():
    global db
    try:
        if not db.is_connected():
            db.reconnect(attempts=3, delay=2)
    except Exception:
        try:
            db = mysql.connector.connect(
                host=os.getenv('DB_HOST', "127.0.0.1"),
                user=os.getenv('DB_USER', "Root"),
                password=os.getenv('DB_PASSWORD', "root"),
                database=os.getenv('DB_NAME', "tcc_reconhece")
            )
        except Exception as e:
            print("Falha ao reconectar DB:", e)

# ---------------- LOGIN ----------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class Usuario(UserMixin):
    def __init__(self, id, nome, email, tipo):
        self.id = id
        self.nome = nome
        self.email = email
        self.tipo = tipo

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    ensure_db_connected()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nome, email, tipo FROM usuarios WHERE id = %s", (user_id,))
        usuario = cursor.fetchone()
        if usuario:
            return Usuario(usuario['id'], usuario['nome'], usuario['email'], usuario.get('tipo'))
    except Exception as e:
        print("Erro load_user:", e)
    finally:
        cursor.close()
    return None

# ---------------- FORMULÁRIOS ----------------
class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    submit = SubmitField("Entrar")

class PessoaForm(FlaskForm):
    nome = StringField("Nome", validators=[DataRequired()])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    endereco_imagem = FileField("Imagem", validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField("Salvar")

# Formulário para criar usuário (para cadastrar_usuario.html)
class UsuarioForm(FlaskForm):
    nome = StringField("Nome", validators=[DataRequired()])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    senha = PasswordField("Senha", validators=[DataRequired()])
    tipo = SelectField("Tipo", choices=[("admin", "Admin"), ("comum", "Comum")], validators=[DataRequired()])
    submit = SubmitField("Criar Usuário")

# ---------------- FUNÇÕES DE BANCO DE DADOS ----------------
def salvar_morador(usuario_id, nome, email, imagem_url):
    ensure_db_connected()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM moradores WHERE email = %s", (email,))
        if cursor.fetchone():
            return False
        cursor.execute(
            "INSERT INTO moradores (usuario_id, nome, email, endereco_imagem) VALUES (%s, %s, %s, %s)",
            (usuario_id, nome, email, imagem_url)
        )
        db.commit()
        return True
    except mysql.connector.errors.IntegrityError as e:
        print("Erro ao inserir morador:", e)
        return False
    finally:
        cursor.close()

def carregar_moradores(usuario_id=None):
    ensure_db_connected()
    cursor = db.cursor(dictionary=True)
    try:
        if usuario_id:
            cursor.execute(
                "SELECT id, usuario_id, nome, email, endereco_imagem, criado_em FROM moradores WHERE usuario_id = %s ORDER BY criado_em DESC",
                (usuario_id,)
            )
        else:
            cursor.execute(
                "SELECT id, usuario_id, nome, email, endereco_imagem, criado_em FROM moradores ORDER BY criado_em DESC"
            )
        return cursor.fetchall()
    finally:
        cursor.close()

def atualizar_morador(email_antigo, email_novo, nome, usuario_id, imagem_url=None):
    ensure_db_connected()
    cursor = db.cursor()
    try:
        if imagem_url:
            sql = "UPDATE moradores SET email = %s, nome = %s, endereco_imagem = %s WHERE usuario_id = %s AND email = %s"
            vals = (email_novo, nome, imagem_url, usuario_id, email_antigo)
        else:
            sql = "UPDATE moradores SET email = %s, nome = %s WHERE usuario_id = %s AND email = %s"
            vals = (email_novo, nome, usuario_id, email_antigo)
        cursor.execute(sql, vals)
        db.commit()
    finally:
        cursor.close()

def excluir_morador(email, usuario_id):
    ensure_db_connected()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM moradores WHERE usuario_id = %s AND email = %s", (usuario_id, email))
        db.commit()
    finally:
        cursor.close()

def imagem_corrigida(pessoas):
    for pessoa in pessoas:
        img = pessoa.get('endereco_imagem')
        if img:
            path_unix = img.replace("\\", "/")
            if "/static/" in path_unix:
                pessoa['endereco_imagem'] = "/static/" + str(path_unix.split("/static/")[-1])
            else:
                pessoa['endereco_imagem'] = "/static/" + os.path.basename(img)
    return pessoas

# ---------------- ROTAS ----------------
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('lista'))
    return redirect(url_for('login'))

# ---------- LOGIN ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        senha = form.password.data

        ensure_db_connected()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
        finally:
            cursor.close()

        if usuario and usuario.get('senha') == senha:
            user = Usuario(usuario['id'], usuario['nome'], usuario['email'], usuario.get('tipo'))
            login_user(user)
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for('lista'))
        else:
            flash("E-mail ou senha inválidos.", "login_danger")

    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logout realizado com sucesso.", "info")
    return redirect(url_for('login'))

# ---------- CADASTRAR ----------
@app.route('/cadastrar', methods=['GET', 'POST'])
@login_required
def cadastrar():
    form = PessoaForm()
    if form.validate_on_submit():
        nome = form.nome.data.strip()
        email = form.email.data.strip().lower()
        uploaded = form.endereco_imagem.data

        moradores = carregar_moradores(current_user.id)
        if any(m.get('email') == email for m in moradores):
            flash("Email já cadastrado.", "warning_cadastro")
            return redirect(url_for('cadastrar'))

        url_imagem = None
        if uploaded and getattr(uploaded, 'filename', None):
            nome_arquivo = secure_filename(uploaded.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            uploaded.save(caminho_arquivo)
            url_imagem = os.path.abspath(caminho_arquivo)

        if salvar_morador(current_user.id, nome, email, url_imagem):
            flash("Morador cadastrado com sucesso!", "success_lista")
            if url_imagem:
                try:
                    enviar_backup_s3(f'uploads/{os.path.basename(url_imagem)}', nome)
                except Exception as e:
                    print("Erro S3:", e)
            return redirect(url_for('lista'))
        else:
            flash("Erro ao cadastrar morador.", "danger_cadastro")

    return render_template('cadastrar.html', form=form)


# ---------- ROTA CADASTRAR NOVO USUÁRIO ----------
@app.route("/cadastrar_usuario", methods=["GET", "POST"])
@login_required
def cadastrar_usuario():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")
        tipo = request.form.get("tipo")

        # Verifica se todos os campos foram preenchidos
        if not nome or not email or not senha or not tipo:
            flash("Preencha todos os campos!", "warning")
            return redirect(url_for("cadastrar_usuario"))

        try:
            cursor = db.cursor()

            # Verifica se o email já existe no banco
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("E-mail já cadastrado!", "warning")
                cursor.close()
                return redirect(url_for("cadastrar_usuario"))

            # Insere o novo usuário
            cursor.execute(
                """
                INSERT INTO usuarios (nome, email, senha, tipo, criado_em)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (nome, email, senha, tipo)
            )
            db.commit()
            cursor.close()

            flash("Usuário cadastrado com sucesso!", "success")
            return redirect(url_for("lista"))

        except Exception as e:
            print("Erro ao cadastrar usuário:", e)
            flash("Erro ao cadastrar usuário.", "danger")
            return redirect(url_for("cadastrar_usuario"))

    # Se for método GET, apenas renderiza a página de cadastro
    return render_template("cadastrar_usuario.html")

# ---------- LISTAR ----------
@app.route('/lista')
@login_required
def lista():
    filtro = request.args.get('filtro', '').strip()
    data = request.args.get('data', '').strip()

    ensure_db_connected()
    cursor = db.cursor(dictionary=True)

    try:
        # Se for admin, mostra todos os moradores e quem os cadastrou
        if current_user.tipo == 'admin':
            query = """
                SELECT 
                    m.id, 
                    m.nome, 
                    m.email, 
                    m.endereco_imagem, 
                    m.criado_em,
                    u.nome AS dono_nome,
                    u.email AS dono_email
                FROM moradores m
                JOIN usuarios u ON m.usuario_id = u.id
                WHERE 1=1
            """
            valores = []

        # Se for comum, mostra apenas os moradores do usuário
        else:
            query = """
                SELECT 
                    m.id, 
                    m.nome, 
                    m.email, 
                    m.endereco_imagem, 
                    m.criado_em,
                    u.nome AS dono_nome,
                    u.email AS dono_email
                FROM moradores m
                JOIN usuarios u ON m.usuario_id = u.id
                WHERE m.usuario_id = %s
            """
            valores = [current_user.id]

        # Aplica filtros, se existirem
        if filtro:
            query += " AND (m.nome LIKE %s OR m.email LIKE %s)"
            filtro_valor = f"%{filtro}%"
            valores.extend([filtro_valor, filtro_valor])

        if data:
            query += " AND DATE(m.criado_em) = %s"
            valores.append(data)

        query += " ORDER BY m.criado_em DESC"

        cursor.execute(query, valores)
        pessoas = cursor.fetchall()

    finally:
        cursor.close()

    pessoas = imagem_corrigida(pessoas)
    return render_template('lista.html', pessoas=pessoas, filtro=filtro, data=data)


# ---------- EDITAR ----------
@app.route('/editar/<email>', methods=['GET', 'POST'])
@login_required
def editar(email):
    ensure_db_connected()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM moradores WHERE usuario_id = %s AND email = %s", (current_user.id, email))
    pessoa = cursor.fetchone()
    cursor.close()

    if not pessoa:
        flash("Morador não encontrado.", "warning")
        return redirect(url_for('lista'))

    pessoa = imagem_corrigida([pessoa])[0]
    form = PessoaForm()
    if request.method == 'GET':
        form.nome.data = pessoa.get('nome')
        form.email.data = pessoa.get('email')

    if form.validate_on_submit():
        nome = form.nome.data.strip()
        novo_email = form.email.data.strip().lower()
        uploaded = form.endereco_imagem.data

        ensure_db_connected()
        c = db.cursor()
        c.execute("SELECT usuario_id FROM moradores WHERE email = %s AND NOT (usuario_id = %s AND email = %s)", (novo_email, current_user.id, email))
        dup = c.fetchone()
        c.close()
        if dup:
            flash("O e-mail informado já está em uso por outro registro.", "danger")
            return redirect(url_for('editar', email=email))

        url_imagem = pessoa.get('endereco_imagem')
        if uploaded and getattr(uploaded, 'filename', None):
            imagem_antiga = pessoa.get('endereco_imagem', '').replace('/static/', '')
            caminho_antigo = os.path.join('static', imagem_antiga)
            if os.path.exists(caminho_antigo):
                os.remove(caminho_antigo)
            nome_arquivo = secure_filename(uploaded.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            uploaded.save(caminho_arquivo)
            url_imagem = os.path.abspath(caminho_arquivo)

        atualizar_morador(email, novo_email, nome, current_user.id, url_imagem)
        flash("Cadastro atualizado com sucesso!", "success_lista")
        return redirect(url_for('lista'))

    return render_template('editar.html', pessoa=pessoa, form=form)

# ---------- EXCLUIR ----------
@app.route('/excluir/<email>', methods=['POST'])
@login_required
def excluir(email):
    ensure_db_connected()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM moradores WHERE usuario_id = %s AND email = %s", (current_user.id, email))
    pessoa = cursor.fetchone()
    cursor.close()

    if pessoa:
        imagem_url = pessoa.get('endereco_imagem', '').replace('/static/', '')
        caminho = os.path.join('static', imagem_url)
        if os.path.exists(caminho):
            os.remove(caminho)

    excluir_morador(email, current_user.id)
    flash("Morador excluído com sucesso!", "success_lista")
    return redirect(url_for('lista'))

# ---------- 2FA ----------
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
        codigo = request.form.get('codigo_2fa', '')
        totp = pyotp.TOTP(secret)
        if totp.verify(codigo, valid_window=1):
            flash("2FA configurado com sucesso! Faça login novamente.", "info")
            logout_user()
            return redirect(url_for('login'))
        else:
            flash("Código 2FA inválido. Tente novamente.", "danger")

    provisioning_url = pyotp.TOTP(secret).provisioning_uri(
        name="admin",
        issuer_name="Sistema de Cadastro Facial"
    )
    return render_template('2fa_setup.html', provisioning_url=provisioning_url)

# ---------- MAIN ----------
if __name__ == '__main__':
    lbd_url = pegar_config("LBD")
    print("LBD URL:", lbd_url)
    if lbd_url:
        try:
            carregar_buffer()
            threading.Thread(target=debounce_worker, daemon=True).start()
        except Exception as e:
            print("Aviso: erro ao iniciar buffer/worker:", e)
        app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        print("[ERROR] Não foi possível pegar config da Lambda, o programa não será iniciado!")

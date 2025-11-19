import os
import threading
import uuid
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from auth_utils import validar_token, gerar_token_reset
from email_service import enviar_email_reset
import resend

# imports locais
from db_connector import (
    get_usuario_by_id, get_usuario_by_email,
    insert_usuario, update_usuario, delete_usuario, list_usuarios, atualizar_senha
)
from forms import LoginForm, UsuarioForm, EditarForm
from utils import pegar_config, enviar_backup_s3, conectado_internet, caminho_imagem_relativo, internet_ativa
from registrar_mudancas import carregar_buffer, debounce_worker
from two_factor import get_or_create_admin_2fa_secret, generate_2fa_qr

# ---------------- CONFIGURAÇÃO ----------------
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or 'dev-secret'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
resend.api_key = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")

# Habilita CSRF
csrf = CSRFProtect(app)

@app.context_processor
def inject_csrf_token():
    """Permite usar {{ csrf_token() }} em formulários sem FlaskForm"""
    return dict(csrf_token=generate_csrf)

# ---------------- LOGIN ----------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class Usuario(UserMixin):
    def __init__(self, id, nome, email, tipo, endereco_imagem=None):
        self.id = id
        self.nome = nome
        self.email = email
        self.tipo = tipo
        self.endereco_imagem = endereco_imagem

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    usuario = get_usuario_by_id(user_id)
    if usuario:
        return Usuario(usuario['id'], usuario['nome'], usuario['email'],
                       usuario.get('tipo'), usuario.get('endereco_imagem'))
    return None

# ---------------- FUNÇÕES AUXILIARES ----------------
def imagem_corrigida(pessoas):
    """Normaliza os caminhos de imagem de cada pessoa"""
    for pessoa in pessoas:
        pessoa['endereco_imagem'] = caminho_imagem_relativo(pessoa.get('endereco_imagem'))
    return pessoas

# ---------------- ROTAS ----------------
@app.route('/')
def index():
    return redirect(url_for('lista')) if current_user.is_authenticated else redirect(url_for('login'))

# ---------- LOGIN ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        senha = form.password.data
        usuario = get_usuario_by_email(email)

        if usuario and usuario.get('senha') == senha:
            user = Usuario(usuario['id'], usuario['nome'], usuario['email'],
                           usuario.get('tipo'), usuario.get('endereco_imagem'))
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

# ---------- CADASTRAR USUÁRIO ----------
@app.route("/cadastrar_usuario", methods=["GET", "POST"])
@login_required
def cadastrar_usuario():
    if current_user.tipo != "admin":
        flash("Apenas administradores podem cadastrar novos usuários!", "danger")
        return redirect(url_for("lista"))

    form = UsuarioForm()
    if form.validate_on_submit():
        nome = form.nome.data.strip()
        email = form.email.data.strip().lower()
        senha = form.senha.data.strip()
        tipo = form.tipo.data
        uploaded = form.endereco_imagem.data

        if get_usuario_by_email(email):
            flash("E-mail já cadastrado!", "warning")
            return redirect(url_for("cadastrar_usuario"))

        url_imagem = None
        if uploaded and getattr(uploaded, 'filename', None):
            nome_arquivo = secure_filename(uploaded.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            uploaded.save(caminho_arquivo)
            url_imagem = os.path.abspath(caminho_arquivo)

            try:
                if conectado_internet():
                    threading.Thread(target=enviar_backup_s3, args=(caminho_arquivo,)).start()
                else:
                    print("Sem Conexão, cadastre novamente o usuário mais tarde para ter o backup da foto!")
            except ImportError:
                print("[AVISO] enviar_backup_s3 não encontrado em utils.py. Upload local apenas.")

        insert_usuario(nome, email, senha, tipo, url_imagem)
        flash("Usuário cadastrado com sucesso!", "success")
        return redirect(url_for("lista"))

    return render_template("cadastrar_usuario.html", form=form)

# ---------- LISTAR ----------
@app.route('/lista')
@login_required
def lista():
    filtro = request.args.get('filtro', '').strip()
    data = request.args.get('data', '').strip()

    pessoas = list_usuarios(
        admin=(current_user.tipo == "admin"),
        user_id=current_user.id,
        filtro=filtro,
        data=data
    )
    pessoas = imagem_corrigida(pessoas)
    status_online = internet_ativa()
    return render_template('lista.html', pessoas=pessoas, filtro=filtro, data=data, status_online=status_online)

# ---------- EDITAR ----------
@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    pessoa = get_usuario_by_id(id)
    if not pessoa:
        flash("Usuário não encontrado.", "editar_danger")
        return redirect(url_for('lista'))

    pessoa['endereco_imagem'] = caminho_imagem_relativo(pessoa.get('endereco_imagem'))

    form = EditarForm()
    if request.method == 'GET':
        form.nome.data = pessoa.get('nome')
        form.email.data = pessoa.get('email')

    if form.validate_on_submit():
        nome = form.nome.data.strip()
        email = form.email.data.strip().lower()
        uploaded = form.endereco_imagem.data

        novo_endereco = pessoa.get('endereco_imagem')
        if uploaded and getattr(uploaded, 'filename', None):
            nome_arquivo = secure_filename(uploaded.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            uploaded.save(caminho_arquivo)
            novo_endereco = os.path.abspath(caminho_arquivo)

            try:
                if conectado_internet():
                    threading.Thread(target=enviar_backup_s3, args=(caminho_arquivo,)).start()
                else:
                    print("Sem Conexão, cadastre novamente o usuário mais tarde para ter o backup da foto!")
            except ImportError:
                print("[AVISO] enviar_backup_s3 não encontrado em utils.py. Upload local apenas.")

        update_usuario(id, nome, email, novo_endereco)
        flash("Informações atualizadas com sucesso!", "editar_success")
        return redirect(url_for('editar', id=id))

    return render_template('editar.html', form=form, pessoa=pessoa)

# ---------- EXCLUIR ----------
@app.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir(id):
    if current_user.tipo != "admin":
        flash("Apenas administradores podem excluir usuários!", "danger")
        return redirect(url_for("lista"))

    usuario = delete_usuario(id)
    if usuario:
        flash("Usuário excluído com sucesso!", "success_lista")
    return redirect(url_for('lista'))

@app.route("/importar_bd")
@login_required
def importar_bd():
    if current_user.tipo != "admin":
        abort(403)
    # lógica aqui
    return redirect(url_for("lista"))

@app.route("/exportar_bd")
@login_required
def exportar_bd():
    if current_user.tipo != "admin":
        abort(403)
    # lógica aqui
    return redirect(url_for("lista"))

@app.route("/resetar_senha/<token>", methods=["GET", "POST"])
def resetar_senha(token):
    # validar token
    data = validar_token(token)

    if not data:
        return "<h1>Link inválido ou expirado.</h1>"

    email = data["email"]  # pegando e-mail do token
    popup = False  # controle para exibir popup no HTML

    if request.method == "POST":
        nova_senha = request.form.get("senha")

        if not nova_senha:
            return "<h1>Senha inválida.</h1>"

        hash_senha = generate_password_hash(nova_senha)
        atualizar_senha(email, nova_senha)

        # Ativar popup no próprio HTML
        popup = True

        return render_template("resetar_senha.html", email=email, popup=popup)

    return render_template("resetar_senha.html", email=email, popup=popup)

@app.route("/esqueci_senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form.get("email")

        # Aqui você valida no banco se o usuário existe
        # usuario = pegar_usuario_por_email(email)
        usuario = True  # Exemplo

        if not usuario:
            return "Usuário não encontrado"

        token = gerar_token_reset(email)
        link = f"http://localhost:5000/resetar_senha/{token}"

        enviar_email_reset(email, link)

        return render_template("esqueci_senha.html", popup=True)

    return render_template("esqueci_senha.html")

# ---------- 2FA ----------
@app.route('/2fa_qr')
def two_factor_qr():
    return generate_2fa_qr()

@app.route('/2fa_setup', methods=['GET', 'POST'])
@login_required
def two_factor_setup():
    import pyotp
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

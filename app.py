import os
import threading
import uuid
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

# imports locais
from db_connector import db, ensure_db_connected
from forms import LoginForm, UsuarioForm, EditarForm
from utils import pegar_config, enviar_backup_s3, conectado_internet, caminho_imagem_relativo
from registrar_mudancas import carregar_buffer, debounce_worker
from two_factor import get_or_create_admin_2fa_secret, generate_2fa_qr

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
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        try:
            cursor.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,))
            usuario = cursor.fetchone()
            if usuario:
                return Usuario(usuario['id'], usuario['nome'], usuario['email'],
                               usuario.get('tipo'), usuario.get('endereco_imagem'))
        except Exception as e:
            print("Erro load_user:", e)
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

        ensure_db_connected()
        with db.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()

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

        ensure_db_connected()
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
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

            cursor.execute(
                """
                INSERT INTO usuarios (nome, email, senha, tipo, endereco_imagem, criado_em)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (nome, email, senha, tipo, url_imagem)
            )
            db.commit()

        flash("Usuário cadastrado com sucesso!", "success")
        return redirect(url_for("lista"))

    return render_template("cadastrar_usuario.html", form=form)

# ---------- LISTAR ----------
@app.route('/lista')
@login_required
def lista():
    filtro = request.args.get('filtro', '').strip()
    data = request.args.get('data', '').strip()

    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        if current_user.tipo == 'admin':
            query = "SELECT * FROM usuarios WHERE 1=1"
            valores = []
        else:
            query = "SELECT * FROM usuarios WHERE id = %s"
            valores = [current_user.id]

        if filtro:
            query += " AND (nome LIKE %s OR email LIKE %s)"
            filtro_valor = f"%{filtro}%"
            valores.extend([filtro_valor, filtro_valor])

        if data:
            query += " AND DATE(criado_em) = %s"
            valores.append(data)

        query += " ORDER BY criado_em DESC"
        cursor.execute(query, valores)
        pessoas = cursor.fetchall()

    pessoas = imagem_corrigida(pessoas)
    return render_template('lista.html', pessoas=pessoas, filtro=filtro, data=data)

# ---------- EDITAR ----------
@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (id,))
        pessoa = cursor.fetchone()

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

        ensure_db_connected()
        with db.cursor() as cursor:
            cursor.execute("""
                UPDATE usuarios 
                SET nome = %s, email = %s, endereco_imagem = %s
                WHERE id = %s
            """, (nome, email, novo_endereco, id))
            db.commit()

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

    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (id,))
        pessoa = cursor.fetchone()

        if pessoa:
            imagem_url = pessoa.get('endereco_imagem', '')
            if imagem_url and os.path.exists(imagem_url):
                os.remove(imagem_url)
            cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
            db.commit()
            flash("Usuário excluído com sucesso!", "success_lista")

    return redirect(url_for('lista'))

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

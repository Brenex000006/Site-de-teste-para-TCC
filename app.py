from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import uuid
import mysql.connector
from datetime import datetime

# Configuração
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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

# Funções de banco de dados
def salvar_usuario(cpf, nome, imagem_url):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (CPF, nome, endereco_imagem) VALUES (%s, %s, %s)",
            (cpf, nome, imagem_url)
        )
        db.commit()
        print(f"Usuário inserido: CPF={cpf}, Nome={nome}, Imagem={imagem_url}")
        return True
    except mysql.connector.errors.IntegrityError as e:
        print("Erro ao inserir CPF:", e)
        return False
    finally:
        cursor.close()

def carregar_usuarios():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()
    cursor.close()
    return usuarios


def atualizar_usuario(cpf_antigo, cpf_novo, nome, imagem_url=None):
    cursor = db.cursor()
    if imagem_url:
        sql = "UPDATE usuarios SET CPF = %s, nome = %s, endereco_imagem = %s WHERE CPF = %s"
        vals = (cpf_novo, nome, imagem_url, cpf_antigo)
    else:
        sql = "UPDATE usuarios SET CPF = %s, nome = %s WHERE CPF = %s"
        vals = (cpf_novo, nome, cpf_antigo)
    cursor.execute(sql, vals)
    db.commit()

def excluir_usuario(cpf):
    cursor = db.cursor()
    cursor.execute("DELETE FROM usuarios WHERE CPF = %s", (cpf,))
    db.commit()

# Rotas
from flask_login import current_user, logout_user

@app.route('/')
def index():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for('login'))
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['username']
        senha = request.form['password']
        if usuario == os.getenv("ADMIN_USERNAME") and senha == os.getenv("ADMIN_PASSWORD"):
            login_user(Admin())
            return redirect(url_for('lista'))
        flash("Credenciais inválidas.")
    return render_template('login.html')

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
        cpf = request.form['identificacao']
        imagem = request.files['imagem']
        # Verifica se CPF já está cadastrado
        usuarios = carregar_usuarios()
        if any(u['cpf'] == cpf for u in usuarios):
            flash("CPF já cadastrado.")
            return redirect(url_for('cadastrar'))

        if imagem:
            nome_arquivo = secure_filename(imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            imagem.save(caminho_arquivo)
            url_imagem = url_for('static', filename=f'uploads/{nome_unico}')
            URL_ABSO = os.path.abspath(caminho_arquivo)

            if salvar_usuario(cpf, nome, URL_ABSO):
                flash("Pessoa cadastrada com sucesso!")
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
        query += " AND (nome LIKE %s OR CPF LIKE %s)"
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

@app.route('/editar/<cpf>', methods=['GET', 'POST'])
@login_required
def editar(cpf):
    usuarios = carregar_usuarios()
    usuarios = imagem_corrigida(usuarios)
    pessoa = next((u for u in usuarios if u['cpf'] == cpf), None)
    if not pessoa:
        flash("Pessoa não encontrada.")
        return redirect(url_for('lista'))

    if request.method == 'POST':
        nome = request.form['nome']
        novo_cpf = request.form['nova_identificacao']
        nova_imagem = request.files.get('imagem')
        nova_url_imagem = pessoa['endereco_imagem']

        if nova_imagem and nova_imagem.filename:
            imagem_antiga = pessoa['endereco_imagem'].replace('/static/', '')
            caminho_antigo = os.path.join('static', imagem_antiga)
            if os.path.exists(caminho_antigo):
                os.remove(caminho_antigo)

            nome_arquivo = secure_filename(nova_imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            nova_imagem.save(caminho_arquivo)
            nova_url_imagem = url_for('static', filename=f'uploads/{nome_unico}')
            Url_Abs = os.path.abspath(caminho_arquivo)
        else:
            relative_path = pessoa['endereco_imagem'].lstrip('/')  # Remove leading slash
            base_dir = os.path.dirname(os.path.abspath(__file__))  # Path to current script
            Url_Abs = os.path.abspath(os.path.join(base_dir, relative_path))

        atualizar_usuario(cpf, novo_cpf, nome, Url_Abs)
        flash("Cadastro atualizado com sucesso!")
        return redirect(url_for('lista'))

    return render_template('editar.html', pessoa=pessoa)

@app.route('/excluir/<cpf>', methods=['POST'])
@login_required
def excluir(cpf):
    usuarios = carregar_usuarios()
    pessoa = next((u for u in usuarios if u['cpf'] == cpf), None)
    if pessoa:
        imagem_url = pessoa.get('endereco_imagem', '').replace('/static/', '')
        caminho = os.path.join('static', imagem_url)
        if os.path.exists(caminho):
            os.remove(caminho)
    excluir_usuario(cpf)
    flash("Registro excluído com sucesso!")
    return redirect(url_for('lista'))

if __name__ == '__main__':
    #app.run(debug=True)
    app.run(host='0.0.0.0', port=5000, debug=True)

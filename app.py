from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import uuid
import json
from datetime import datetime

# Configuração
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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

# Utilitários
JSON_PATH = 'cadastros.json'

def carregar_dados():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r') as f:
            return json.load(f)
    return []

def salvar_dados(pessoa):
    dados = carregar_dados()
    if any(p['identificacao'] == pessoa['identificacao'] for p in dados):
        return False
    dados.append(pessoa)
    with open(JSON_PATH, 'w') as f:
        json.dump(dados, f, indent=4)
    return True

def atualizar_dados(identificacao, novos_dados):
    dados = carregar_dados()
    for i, p in enumerate(dados):
        if p['identificacao'] == identificacao:
            dados[i].update(novos_dados)
            with open(JSON_PATH, 'w') as f:
                json.dump(dados, f, indent=4)
            return True
    return False

def excluir_dado(identificacao):
    dados = carregar_dados()
    novos_dados = [p for p in dados if p['identificacao'] != identificacao]
    with open(JSON_PATH, 'w') as f:
        json.dump(novos_dados, f, indent=4)
    return True

# Rotas
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['username']
        senha = request.form['password']
        if usuario == os.getenv("ADMIN_USERNAME") and senha == os.getenv("ADMIN_PASSWORD"):
            login_user(Admin())
            return redirect(url_for('cadastrar'))
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
        identificacao = request.form['identificacao']
        imagem = request.files['imagem']

        # Verifica se identificação já está cadastrada
        dados = carregar_dados()
        if any(p['identificacao'] == identificacao for p in dados):
            flash("Identificação já cadastrada.")
            return redirect(url_for('cadastrar'))

        # Só salva imagem se a identificação for nova
        if imagem:
            nome_arquivo = secure_filename(imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            imagem.save(caminho_arquivo)
            url_imagem = url_for('static', filename=f'uploads/{nome_unico}')

            pessoa = {
                "nome": nome,
                "identificacao": identificacao,
                "imagem_url": url_imagem,
                "data": datetime.now().strftime("%Y-%m-%d")
            }

            salvar_dados(pessoa)
            flash("Pessoa cadastrada com sucesso!")
            return redirect(url_for('cadastrar'))

    return render_template('cadastrar.html')


@app.route('/lista')
@login_required
def lista():
    pessoas = carregar_dados()
    busca = request.args.get('busca', '').strip().lower()
    data_filtro = request.args.get('data', '').strip()

    if busca:
        pessoas = [p for p in pessoas if busca in p['nome'].lower() or busca in p['identificacao'].lower()]

    if data_filtro:
        pessoas = [p for p in pessoas if p.get('data') == data_filtro]

    return render_template('lista.html', pessoas=pessoas, busca=busca, data_filtro=data_filtro)

@app.route('/editar/<identificacao>', methods=['GET', 'POST'])
@login_required
def editar(identificacao):
    dados = carregar_dados()
    pessoa = next((p for p in dados if p['identificacao'] == identificacao), None)
    if not pessoa:
        flash("Pessoa não encontrada.")
        return redirect(url_for('lista'))

    if request.method == 'POST':
        nome = request.form['nome']
        nova_identificacao = request.form['nova_identificacao']
        nova_imagem = request.files.get('imagem')
        nova_url_imagem = pessoa['imagem_url']

        # Se nova imagem foi enviada, remove a anterior e salva a nova
        if nova_imagem and nova_imagem.filename:
            imagem_antiga = pessoa.get('imagem_url', '').replace('/static/', '')
            caminho_antigo = os.path.join('static', imagem_antiga)
            if os.path.exists(caminho_antigo):
                os.remove(caminho_antigo)

            nome_arquivo = secure_filename(nova_imagem.filename)
            nome_unico = f"{uuid.uuid4()}_{nome_arquivo}"
            caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], nome_unico)
            nova_imagem.save(caminho_arquivo)
            nova_url_imagem = url_for('static', filename=f'uploads/{nome_unico}')

        # Atualiza ou move o registro
        dados = [p for p in dados if p['identificacao'] != identificacao]
        pessoa_atualizada = {
            "nome": nome,
            "identificacao": nova_identificacao,
            "imagem_url": nova_url_imagem,
            "data": pessoa.get("data", datetime.now().strftime("%Y-%m-%d"))
        }

        # Garante que a nova identificação não já esteja em uso
        if any(p['identificacao'] == nova_identificacao for p in dados):
            flash("Essa nova identificação já está em uso.")
            return redirect(url_for('editar', identificacao=identificacao))

        dados.append(pessoa_atualizada)
        with open(JSON_PATH, 'w') as f:
            json.dump(dados, f, indent=4)

        flash("Cadastro atualizado com sucesso!")
        return redirect(url_for('lista'))

    return render_template('editar.html', pessoa=pessoa)



@app.route('/excluir/<identificacao>', methods=['POST'])
@login_required
def excluir(identificacao):
    dados = carregar_dados()
    pessoa = next((p for p in dados if p['identificacao'] == identificacao), None)
    if pessoa:
        # Remove imagem do disco
        imagem_url = pessoa.get('imagem_url', '').replace('/static/', '')
        caminho = os.path.join('static', imagem_url)
        if os.path.exists(caminho):
            os.remove(caminho)
    excluir_dado(identificacao)
    flash("Registro excluído com sucesso!")
    return redirect(url_for('lista'))


if __name__ == '__main__':
    app.run(debug=True)

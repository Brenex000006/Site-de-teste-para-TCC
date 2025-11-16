import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
id_conta = os.getenv("CONTA_ID")
print(id_conta)
# ---------------- CONEXÃO ----------------
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

# ---------------- FUNÇÕES DE USUÁRIO ----------------
def get_usuario_by_id(user_id):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,))
        return cursor.fetchone()

def get_usuario_by_email(email):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        return cursor.fetchone()

def insert_usuario(nome, email, senha, tipo, endereco_imagem):
    global id_conta
    ensure_db_connected()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO usuarios (nome, email, senha, tipo, endereco_imagem, criado_em)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (nome, email, senha, tipo, endereco_imagem)
        )
        db.commit()

def update_usuario(id, nome, email, endereco_imagem):
    ensure_db_connected()
    with db.cursor() as cursor:
        cursor.execute(
            """
            UPDATE usuarios 
            SET nome = %s, email = %s, endereco_imagem = %s
            WHERE id = %s
            """,
            (nome, email, endereco_imagem, id)
        )
        db.commit()

def delete_usuario(id):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (id,))
        usuario = cursor.fetchone()
        if usuario:
            imagem_url = usuario.get('endereco_imagem', '')
            if imagem_url and os.path.exists(imagem_url):
                os.remove(imagem_url)
            cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
            db.commit()
        return usuario

def list_usuarios(admin=False, user_id=None, filtro=None, data=None):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        if admin:
            query = "SELECT * FROM usuarios"
            valores = []
        else:
            query = "SELECT * FROM usuarios WHERE id = %s"
            valores = [user_id]

        if filtro:
            query += " AND (nome LIKE %s OR email LIKE %s)"
            filtro_valor = f"%{filtro}%"
            valores.extend([filtro_valor, filtro_valor])

        if data:
            query += " AND DATE(criado_em) = %s"
            valores.append(data)

        query += " ORDER BY criado_em DESC"
        cursor.execute(query, valores)
        return cursor.fetchall()

# ---------------- SUPORTE AO SISTEMA DE RESET DE SENHA ----------------

def atualizar_senha(email, nova_senha):
    ensure_db_connected()
    with db.cursor() as cursor:
        cursor.execute("""
            UPDATE usuarios
            SET senha = %s
            WHERE email = %s
        """, (nova_senha, email))
        db.commit()

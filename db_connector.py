import os
from pprint import pprint

import mysql.connector
from dotenv import load_dotenv
from utils import pegar_config_DB, conectado_internet, internet_ativa

# ---------------- CONFIG AMBIENTE ----------------
load_dotenv()
id_conta = os.getenv("CONTA_ID")
rds_config = pegar_config_DB("RDS")
mysql_config = pegar_config_DB("MYSQL")

# ---------------- CONEXÃO ----------------
# if conectado_internet():
if internet_ativa():
    config_escolhida = rds_config
else:
    config_escolhida = mysql_config
db = mysql.connector.connect(
    host=config_escolhida["host"],
    user=config_escolhida["user"],
    password=config_escolhida["password"],
    database=config_escolhida["database"],
)

def ensure_db_connected():
    global db
    try:
        if not db.is_connected():
            db.reconnect(attempts=3, delay=2)
    except Exception:
        try:
            # if conectado_internet():
            if internet_ativa():
                config_escolhida = rds_config
            else:
                config_escolhida = mysql_config
            db = mysql.connector.connect(
                host=config_escolhida["host"],
                user=config_escolhida["user"],
                password=config_escolhida["password"],
                database=config_escolhida["database"],
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
            INSERT INTO usuarios (nome, email, senha, tipo, endereco_imagem, conta_id, criado_em)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (nome, email, senha, tipo, endereco_imagem, id_conta)
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
            query = "SELECT * FROM usuarios where conta_id = %s"
            valores = [id_conta]
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
def salvar_token_reset(email, token):
    ensure_db_connected()
    with db.cursor() as cursor:
        cursor.execute("""
            UPDATE usuarios
            SET reset_token = %s,
                reset_expires = DATE_ADD(NOW(), INTERVAL 30 MINUTE)
            WHERE email = %s
        """, (token, email))
        db.commit()

def validar_token(token):
    ensure_db_connected()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("""
            SELECT * FROM usuarios
            WHERE reset_token = %s
              AND reset_expires > NOW()
        """, (token,))
        return cursor.fetchone()

def atualizar_senha(email, nova_senha):
    ensure_db_connected()
    with db.cursor() as cursor:
        cursor.execute("""
            UPDATE usuarios
            SET senha = %s,
                reset_token = NULL,
                reset_expires = NULL
            WHERE email = %s
        """, (nova_senha, email))
        db.commit()

# ----- BACKUP AWS (DA AWS) -----
import mysql.connector


def fetch_from_aws():
    global rds_config, id_conta
    aws_db = mysql.connector.connect(
        host=rds_config["host"],
        user=rds_config["user"],
        password=rds_config["password"],
        database=rds_config["database"],
    )

    cursor = aws_db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nome, email, senha, tipo, criado_por, conta_id, criado_em, endereco_imagem
        FROM usuarios
        WHERE conta_id = %s
    """, (id_conta,))

    users = cursor.fetchall()
    cursor.close()
    aws_db.close()
    return users


def sync_to_local(users):
    global mysql_config
    local_db = mysql.connector.connect(
        host=mysql_config["host"],
        user=mysql_config["user"],
        password=mysql_config["password"],
        database=mysql_config["database"],
    )
    cursor = local_db.cursor()

    for user in users:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, tipo, criado_por, conta_id, endereco_imagem)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                nome = VALUES(nome),
                senha = VALUES(senha),
                tipo = VALUES(tipo),
                criado_por = VALUES(criado_por),
                conta_id = VALUES(conta_id),
                endereco_imagem = VALUES(endereco_imagem);
        """, (
            user["nome"],
            user["email"],
            user["senha"],
            user["tipo"],
            user["criado_por"],
            user["conta_id"],
            user["endereco_imagem"]
        ))

    local_db.commit()
    cursor.close()
    local_db.close()


def delete_local_not_in(users, conta_id): #Não usar por enquanto
    local_db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="tcc_reconhece"
    )
    cursor = local_db.cursor()

    emails = tuple(user["email"] for user in users)

    if not emails:
        # if AWS has no users for that conta, delete all in local
        cursor.execute("DELETE FROM usuarios WHERE conta_id = %s", (conta_id,))
    else:
        query = f"""
            DELETE FROM usuarios
            WHERE conta_id = %s AND email NOT IN ({','.join(['%s'] * len(emails))})
        """
        cursor.execute(query, (conta_id, *emails))

    local_db.commit()
    cursor.close()
    local_db.close()

# ----- BACKUP AWS (PARA AWS) -----
def fetch_from_local(conta_id):
    local_db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="tcc_reconhece"
    )

    cursor = local_db.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, nome, email, senha, tipo, criado_por, conta_id, criado_em, endereco_imagem
        FROM usuarios
        WHERE conta_id = %s
    """, (conta_id,))

    users = cursor.fetchall()
    cursor.close()
    local_db.close()
    return users

# ----- Backup Generico -----
def pegar_usuarios(tipo_db):
    global id_conta
    if tipo_db == "RDS":
        db_config = rds_config
    else:
        db_config = mysql_config
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nome, email, senha, tipo, criado_por, conta_id, criado_em, endereco_imagem
        FROM usuarios
        WHERE conta_id = %s
    """, (id_conta,))

    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users

def att_usuarios(tipo_db, users):
    if tipo_db == "RDS":
        db_config = rds_config
    else:
        db_config = mysql_config
    pprint(db_config)
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    for user in users:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, tipo, criado_por, conta_id, endereco_imagem)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                nome = VALUES(nome),
                senha = VALUES(senha),
                tipo = VALUES(tipo),
                criado_por = VALUES(criado_por),
                conta_id = VALUES(conta_id),
                endereco_imagem = VALUES(endereco_imagem)
        """, (
            user["nome"],
            user["email"],
            user["senha"],
            user["tipo"],
            user["criado_por"],
            user["conta_id"],
            user["endereco_imagem"]
        ))

    conn.commit()
    cursor.close()
    conn.close()
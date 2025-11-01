import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# Cria conexão inicial
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', "127.0.0.1"),
        user=os.getenv('DB_USER', "Root"),
        password=os.getenv('DB_PASSWORD', "root"),
        database=os.getenv('DB_NAME', "tcc_reconhece")
    )

# Conexão global reutilizável
db = get_db_connection()

def ensure_db_connected():
    """Verifica e reconecta ao banco, se necessário."""
    global db
    try:
        if not db.is_connected():
            db.reconnect(attempts=3, delay=2)
    except Exception:
        db = get_db_connection()

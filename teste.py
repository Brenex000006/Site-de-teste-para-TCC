import mysql.connector

try:
    db = mysql.connector.connect(
        host="127.0.0.1",
        user="Root",
        password="root",
        database="tcc_reconhece"
    )
    print("Conexão OK")
    db.close()
except mysql.connector.Error as err:
    print("Erro:", err)

import jwt
import datetime
import os

SECRET_KEY = os.getenv("SECRET_KEY")

def gerar_token_reset(email):
    payload = {
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def validar_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception as e:
        print("Erro JWT:", e)
        return None


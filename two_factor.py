import os
import io
import pyotp
import qrcode
from dotenv import load_dotenv
from flask import send_file

load_dotenv()

def update_env_variable(key, value, env_path='.env'):
    """Atualiza ou adiciona uma variável no arquivo .env"""
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    with open(env_path, 'w', encoding='utf-8') as f:
        found = False
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
    """Retorna a chave secreta do admin ou cria uma nova"""
    secret = os.getenv('ADMIN_2FA_SECRET')
    if not secret:
        secret = pyotp.random_base32()
        update_env_variable('ADMIN_2FA_SECRET', secret)
    return secret

def generate_2fa_qr():
    """Gera o QR Code do 2FA"""
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

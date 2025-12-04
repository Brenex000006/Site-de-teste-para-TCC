import os
import io
import hmac
import hashlib
import base64
import pyotp
import qrcode
from dotenv import load_dotenv
from flask import send_file, redirect, session, url_for
from flask_login import current_user

load_dotenv()

# -----------------------
# DECORATOR DO 2FA
# -----------------------
def require_2fa(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))

        if not session.get("2fa_ok"):
            return redirect(url_for("two_factor_setup"))

        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


# -----------------------
# FUNÇÕES PARA 2FA ÚNICO POR ADMIN
# -----------------------
def generate_user_secret(user_id: int, senha_hash: str):
    """
    Gera chave 2FA única para cada admin:
    → Derivada do hash da senha + ID do admin
    → Não salva em nenhum lugar
    → Consistente toda vez que ele logar
    """
    key = hmac.new(
        senha_hash.encode(),
        msg=str(user_id).encode(),
        digestmod=hashlib.sha1
    ).digest()

    return base64.b32encode(key).decode()


def get_or_create_admin_2fa_secret(usuario: dict):
    """
    Retorna o segredo único do admin.
    Agora NÃO usa mais .env nem ADMIN_2FA_SECRET.
    """
    return generate_user_secret(usuario["id"], usuario["email"])


# -----------------------
# GERAR QR CODE
# -----------------------
def generate_2fa_qr(secret, email):
    """
    Gera QR Code para Google Authenticator.
    """
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=email,
        issuer_name="Sistema de Reconhecimento Facial"
    )

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

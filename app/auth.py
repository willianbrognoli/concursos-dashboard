"""Autenticação: senha bcrypt + sessão em cookie assinado."""
import os

import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer

SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-no-easypanel")
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", 60 * 60 * 24 * 14))  # 14 dias
COOKIE_NAME = "cd_session"

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="cd-auth")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str):
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("uid")
    except BadSignature:
        return None
    except Exception:
        return None

"""Пароли и сессии.

Пароли хешируются scrypt из стандартной библиотеки: отдельная зависимость не
нужна, а scrypt специально сделан медленным, чтобы перебор был бесполезен.

Сессия - подписанная cookie. Никаких токенов в localStorage: их можно украсть
скриптом со страницы, а cookie с флагом httponly недоступна из JavaScript.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from winnow.web.core import SECRET, SESSION_DAYS, User, get_db

COOKIE_NAME = "winnow_session"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """Возвращает строку вида «scrypt$n$r$p$соль$хеш»."""
    if len(password) < 8:
        raise ValueError("Пароль должен быть не короче 8 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(hash_b64)
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def _sign(payload: str) -> str:
    return hmac.new(SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_token(user_id: int) -> str:
    """Подписанный токен сессии: «идентификатор.срок.подпись»."""
    expires = int(time.time()) + SESSION_DAYS * 24 * 3600
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> int | None:
    """Возвращает идентификатор пользователя или None, если токен негоден."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id, expires, signature = parts
    payload = f"{user_id}.{expires}"
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    try:
        if int(expires) < time.time():
            return None
        return int(user_id)
    except ValueError:
        return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Зависимость: пользователь из cookie или 401."""
    token = request.cookies.get(COOKIE_NAME)
    user_id = read_token(token) if token else None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужно войти в систему",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия устарела, войдите заново",
        )
    return user


__all__ = [
    "COOKIE_NAME",
    "current_user",
    "hash_password",
    "issue_token",
    "read_token",
    "verify_password",
]

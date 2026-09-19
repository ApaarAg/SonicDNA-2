import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


TOKEN_PREFIX = "enc:v1:"


def _configured_secret() -> str:
    return (
        os.getenv("SPOTIFY_TOKEN_ENCRYPTION_KEY")
        or os.getenv("SESSION_TOKEN_SECRET")
        or os.getenv("GROQ_API_KEY")
        or "sonicdna-local-token-encryption"
    )


def token_encryption_configured() -> bool:
    return bool(os.getenv("SPOTIFY_TOKEN_ENCRYPTION_KEY"))


def _fernet_key(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    try:
        Fernet(raw)
        return raw
    except Exception:
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_fernet_key(_configured_secret()))


def is_encrypted_token(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(TOKEN_PREFIX)


def encrypt_token(value: Optional[str]) -> str:
    if not value:
        return ""
    if is_encrypted_token(value):
        return value
    encrypted = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{TOKEN_PREFIX}{encrypted}"


def decrypt_token(value: Optional[str]) -> str:
    if not value:
        return ""
    if not is_encrypted_token(value):
        return value
    payload = value[len(TOKEN_PREFIX):].encode("utf-8")
    try:
        return _fernet().decrypt(payload).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored Spotify token could not be decrypted") from exc

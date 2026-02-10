"""AES-256-GCM encryption/decryption for Pyrogram StringSession data.

Encryption key is read from SESSION_ENC_KEY env var (32-byte hex or base64).
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LENGTH = 12  # 96-bit nonce for GCM


def _get_key() -> bytes:
    raw = os.environ.get("SESSION_ENC_KEY", "")
    if not raw:
        from app.core.settings import get_settings
        raw = getattr(get_settings(), "session_enc_key", "")
    if not raw:
        raise RuntimeError("SESSION_ENC_KEY is not set")
    # Accept hex (64 chars for 32 bytes) or base64
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.b64decode(raw)
        except Exception:
            # Fallback: SHA-256 hash of the raw string
            key = hashlib.sha256(raw.encode()).digest()
    if len(key) != 32:
        key = hashlib.sha256(key).digest()
    return key


def encrypt_session(plaintext: str) -> str:
    """Encrypt a Pyrogram StringSession string -> base64 ciphertext."""
    key = _get_key()
    nonce = os.urandom(_NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_session(ciphertext: str) -> str:
    """Decrypt base64 ciphertext -> Pyrogram StringSession string."""
    key = _get_key()
    raw = base64.b64decode(ciphertext)
    nonce = raw[:_NONCE_LENGTH]
    ct = raw[_NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ct, None)
    return plaintext.decode("utf-8")

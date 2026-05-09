"""Fernet encryption for user-supplied secrets (DeepSeek API keys).

Phase 2 only writes; reads happen in v2 when the "bring your own key" path is
implemented.

If FERNET_KEY is missing in dev, a transient key is generated. Restarting the
process invalidates anything previously stored — fine while we're not yet using
the encrypted data. **Set a permanent key in prod.**
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet

from app.config import settings

log = logging.getLogger(__name__)


def _make_fernet() -> Fernet:
    key = settings.fernet_key.strip()
    if not key:
        key = Fernet.generate_key().decode()
        log.warning(
            "FERNET_KEY not set; generated a transient key. "
            "Encrypted data will not survive process restarts. "
            "Set FERNET_KEY in .env for persistence."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


_fernet = _make_fernet()


def encrypt(plain: str) -> str:
    """Encrypt a plaintext string. Returns a URL-safe base64 token."""
    return _fernet.encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token previously produced by encrypt()."""
    return _fernet.decrypt(token.encode()).decode()

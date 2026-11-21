# SPDX-License-Identifier: GPL-3.0-or-later
"""Authentication of the admin API: one admin user with HTTP Basic Auth.

The password is stored as a scrypt hash in the .env (create it with `python admin_passwd.py`):
    ADMIN_USER=admin
    ADMIN_PASSWORD_HASH=scrypt$16384$8$1$<salt>$<hash>

Without ADMIN_PASSWORD_HASH the whole admin API is disabled (fail closed).
Requests that change data must send the header  X-Requested-With: bert-admin  (protects against
cross-site requests: a foreign web page cannot add this header without a CORS preflight).
"""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import config  # noqa: F401  (loads the .env)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()

# Failed logins per client address: too many in a time window block that address for a while.
MAX_FAILURES = 10
WINDOW_SECONDS = 600

_security = HTTPBasic(auto_error=False)
_failures: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    """Create a hash string for the .env."""
    n, r, p = 2**14, 8, 1
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)))
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


def _blocked(address: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _failures.get(address, []) if now - t < WINDOW_SECONDS]
    _failures[address] = recent
    return len(recent) >= MAX_FAILURES


def _register_failure(address: str) -> None:
    _failures.setdefault(address, []).append(time.monotonic())


def admin_auth(request: Request, credentials: HTTPBasicCredentials | None = Depends(_security)) -> str:
    """FastAPI dependency: returns the admin user name or raises 401/403/429/503."""
    if not ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Admin API is not configured (ADMIN_PASSWORD_HASH is missing)")

    address = request.client.host if request.client else "unknown"
    if _blocked(address):
        raise HTTPException(status_code=429, detail="Too many failed logins, try again later",
                            headers={"Retry-After": str(WINDOW_SECONDS)})

    if credentials is None:  # the browser has not sent credentials yet: ask for them
        raise HTTPException(status_code=401, detail="Login required",
                            headers={"WWW-Authenticate": 'Basic realm="Bert admin"'})

    # Always check the password (also for a wrong user name) so the timing reveals nothing.
    user_ok = hmac.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    password_ok = verify_password(credentials.password, ADMIN_PASSWORD_HASH)
    if not (user_ok and password_ok):
        _register_failure(address)
        raise HTTPException(status_code=401, detail="Wrong user name or password",
                            headers={"WWW-Authenticate": 'Basic realm="Bert admin"'})

    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "bert-admin":
        raise HTTPException(status_code=403, detail="Header 'X-Requested-With: bert-admin' is required")
    return credentials.username
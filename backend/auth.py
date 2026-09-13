"""
Authentication for the CBDC Fraud Detection SaaS layer
==========================================================
Two separate auth mechanisms, for two separate audiences:

1. JWT session tokens — for a human logging into the dashboard/admin UI
   (POST /auth/login). Short-lived, sent as a Bearer token.

2. API keys — for a paying customer's backend calling the fraud-check API
   programmatically (POST /transaction with an X-API-Key header). Long-lived
   until revoked, identifies which organization the call belongs to.

Passwords are hashed with bcrypt (via passlib) — never stored in plaintext.
API keys are stored as SHA-256 hashes — the plaintext key is shown to the
customer exactly once, at creation time, and cannot be retrieved again
(same pattern Stripe, AWS, etc. use for API keys).
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Header, status

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# In production, set JWT_SECRET as a real environment variable — this
# fallback is only for local development so the app doesn't crash if unset.
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT session tokens (for dashboard login)
# ---------------------------------------------------------------------------
def create_access_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency: protects dashboard/management endpoints with a
    JWT Bearer token. Usage: user = Depends(get_current_user)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    return {"user_id": int(payload["sub"]), "email": payload["email"]}


# ---------------------------------------------------------------------------
# API keys (for programmatic access to the fraud-check API)
# ---------------------------------------------------------------------------
def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key, key_prefix, key_hash).
    plaintext_key is shown to the user ONCE and never stored.
    key_prefix (first 12 chars) is stored so the user can identify which
    key is which in a list, without exposing the full secret.
    key_hash is what's actually stored and checked against on each request."""
    plaintext_key = "sk_live_" + secrets.token_urlsafe(32)
    key_prefix = plaintext_key[:16]
    key_hash = hashlib.sha256(plaintext_key.encode()).hexdigest()
    return plaintext_key, key_prefix, key_hash


def hash_api_key(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode()).hexdigest()

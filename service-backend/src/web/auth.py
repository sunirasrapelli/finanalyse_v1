"""
Google OAuth2 + JWT authentication for FinAnalyse.

Flow
----
1. Client navigates to GET /auth/google
2. Server redirects to Google's OAuth consent page
3. Google redirects to GET /auth/callback?code=...
4. Server exchanges code → access token → user info
5. Server upserts user row → issues JWT
6. Redirects to FRONTEND_URL?token=<jwt>  (frontend stores in localStorage)
7. Subsequent requests include  Authorization: Bearer <token>

FastAPI dependencies
--------------------
  get_current_user   — raises 401 when no valid token
  get_optional_user  — returns None when no valid token (for optional auth)
"""
import os
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

# ── Configuration (from environment) ──────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")
JWT_SECRET           = os.getenv("JWT_SECRET", "change-me-in-production-please")
JWT_ALGORITHM        = "HS256"
JWT_EXPIRE_DAYS      = 30

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_bearer = HTTPBearer(auto_error=False)


# ── Capability check ──────────────────────────────────────────────────────────

def google_auth_enabled() -> bool:
    """True only when both Google OAuth credentials are configured."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ── OAuth helpers ─────────────────────────────────────────────────────────────

def build_google_auth_url() -> str:
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "prompt":        "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_code_for_user(code: str) -> dict:
    """
    Exchange an OAuth authorization code for a Google user-info dict.
    Returns: {google_id, email, name, picture}
    Raises httpx.HTTPStatusError on any Google API error.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        user_resp.raise_for_status()
        info = user_resp.json()

    return {
        "google_id": info["sub"],
        "email":     info.get("email", ""),
        "name":      info.get("name", ""),
        "picture":   info.get("picture", ""),
    }


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub":   user_id,
        "email": email,
        "exp":   datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
        "iat":   datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── FastAPI dependency functions ──────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Require a valid JWT. Raises 401 otherwise."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = _decode_jwt(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"user_id": payload["sub"], "email": payload.get("email", "")}


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising 401."""
    if not credentials:
        return None
    try:
        payload = _decode_jwt(credentials.credentials)
        return {"user_id": payload["sub"], "email": payload.get("email", "")}
    except JWTError:
        return None

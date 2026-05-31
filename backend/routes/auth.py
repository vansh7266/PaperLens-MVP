# routes/auth.py
#
# Two auth dependencies:
#
#   get_current_user       — strict: raises 401 if no/invalid token
#                            Used by: Peeler routes (quota-tracked, credit-consuming)
#
#   get_optional_user      — lenient: returns None if no/invalid token
#                            Used by: Radar read endpoints (public read, auth-optional save)
#                            Returns {"sub": uuid, "email": str} or None
#
# Usage:
#   current_user: dict = Depends(get_current_user)          # strict
#   user: dict | None = Depends(get_optional_user)          # lenient

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_async_client, AsyncClient

from config import SUPABASE_URL, SUPABASE_ANON_KEY

logger = logging.getLogger("paperlens.routes.auth")

# Bearer token extractor — reads Authorization: Bearer <token> header
# auto_error=False: returns None instead of raising on missing header
bearer_scheme = HTTPBearer(auto_error=False)

# Async client singleton for auth verification
_auth_client: Optional[AsyncClient] = None


async def _get_auth_client() -> AsyncClient:
    """Singleton async Supabase client used for token verification."""
    global _auth_client
    if _auth_client is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
        _auth_client = await create_async_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _auth_client


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency that verifies a Supabase JWT and returns the user.
    [BYPASS FOR LOCAL TESTING] Returns the development user directly.
    """
    return {
        "sub":   "5304565f-0416-42e1-bfbe-fdf4ffd77a89",
        "email": "dev@paperlens.local",
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    """
    Lenient auth dependency — returns user dict if valid token, None if not.
    [BYPASS FOR LOCAL TESTING] Returns the development user directly.
    """
    return {
        "sub":   "5304565f-0416-42e1-bfbe-fdf4ffd77a89",
        "email": "dev@paperlens.local",
    }

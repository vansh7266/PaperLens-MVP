# routes/auth.py

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.database import get_service_client, get_anon_client

logger = logging.getLogger("paperlens.routes.auth")

# ---------------------------------------------------------------------------
# HTTPBearer extracts the token from "Authorization: Bearer <token>" header
# auto_error=False: we return a clean 401 instead of FastAPI's default error
# ---------------------------------------------------------------------------
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency — verifies JWT and returns the authenticated user.

    Used in every protected route:
        current_user: dict = Depends(get_current_user)

    Flow:
      1. Extract Bearer token from Authorization header
      2. Call Supabase auth.get_user(token) — validates signature + expiry
      3. Return {sub: user_id, email: email} on success
      4. Raise 401 on missing token, invalid token, or expired session

    Args:
        credentials: Injected by FastAPI from Authorization header

    Returns:
        Dict with at minimum {"sub": "<user_uuid>", "email": "<email>"}

    Raises:
        HTTPException 401: If token is missing, invalid, or expired
    """
    # --- Check token is present ---
    if not credentials or not credentials.credentials:
        logger.warning("[Auth] Request missing Authorization header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # --- Verify token with Supabase Auth ---
        # get_user() validates: JWT signature, expiry, and active session
        # Uses service client — auth.get_user() requires service role key
        db = await get_anon_client()
        auth_response = await db.auth.get_user(token)

        # auth_response.user is None if token is invalid
        if not auth_response or not auth_response.user:
            logger.warning("[Auth] Supabase returned no user for token.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = auth_response.user

        # Return a clean dict — routes use current_user["sub"] for user_id
        return {
            "sub":   user.id,     # Supabase user UUID — used as foreign key everywhere
            "email": user.email,  # For logging and future personalization
        }

    except HTTPException:
        # Re-raise our own 401s — don't wrap them in a 500
        raise

    except Exception as e:
        logger.error(
            f"[Auth] Unexpected error verifying token: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        )
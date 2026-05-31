# radar/core/database.py
#
# Async Supabase client singletons for the Research Radar module.
# Uses supabase-py v2 async client — non-blocking, safe for FastAPI event loop.
#
# Separate from core/database.py (Paper Peeler) — Radar uses async client,
# Peeler uses sync client. Both coexist without conflict.

import logging
from typing import Optional

from supabase import create_async_client, AsyncClient

from config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY

logger = logging.getLogger("paperlens.radar.core.database")

# Singleton instances — created once at startup, reused forever
_service_client: Optional[AsyncClient] = None
_anon_client:    Optional[AsyncClient] = None


async def get_service_client() -> AsyncClient:
    """
    Async Supabase service role client (singleton).

    Bypasses Row Level Security — used only for:
      - Pipeline internals (processor, summarizer, scheduler)
      - Admin operations (releasing free tier batch)

    NEVER use for user-facing routes.
    """
    global _service_client

    if _service_client is not None:
        return _service_client

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "[Radar DB] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env"
        )

    try:
        _service_client = await create_async_client(
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_SERVICE_KEY,
        )
        logger.info("[Radar DB] Async service role client initialized.")
        return _service_client
    except Exception as e:
        logger.error(
            f"[Radar DB] Failed to initialize service client: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise RuntimeError(f"[Radar DB] Service client init failed: {e}") from e


async def get_anon_client() -> AsyncClient:
    """
    Async Supabase anon client (singleton).

    Respects Row Level Security — used for all user-facing API routes.
    Users can only see/modify their own rows where RLS policies enforce it.
    """
    global _anon_client

    if _anon_client is not None:
        return _anon_client

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "[Radar DB] SUPABASE_URL or SUPABASE_ANON_KEY not set in .env"
        )

    try:
        _anon_client = await create_async_client(
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_ANON_KEY,
        )
        logger.info("[Radar DB] Async anon client initialized.")
        return _anon_client
    except Exception as e:
        logger.error(
            f"[Radar DB] Failed to initialize anon client: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise RuntimeError(f"[Radar DB] Anon client init failed: {e}") from e


async def reset_clients() -> None:
    """Reset both singletons. For test use only."""
    global _service_client, _anon_client
    _service_client = None
    _anon_client    = None
    logger.debug("[Radar DB] Clients reset (test use only).")

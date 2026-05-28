# core/database.py

import logging
from typing import Optional

from supabase import create_async_client, AsyncClient

import config

logger = logging.getLogger("paperlens.core.database")

# Singleton instances — async clients, initialized once at startup
_service_client: Optional[AsyncClient] = None
_anon_client: Optional[AsyncClient] = None


async def get_service_client() -> AsyncClient:
    """
    Return the async Supabase service role client (singleton).

    Async because create_async_client() must be awaited.
    Singleton: first call initializes, subsequent calls return cached instance.

    USE FOR: pipeline internals (processor, summarizer, scheduler)
    NEVER FOR: API routes or frontend-facing queries
    """
    global _service_client

    if _service_client is not None:
        return _service_client

    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "[Database] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set."
        )

    try:
        _service_client = await create_async_client(
            supabase_url=config.SUPABASE_URL,
            supabase_key=config.SUPABASE_SERVICE_ROLE_KEY,
        )
        logger.info("[Database] Async service role client initialized.")
        return _service_client

    except Exception as e:
        logger.error(
            f"[Database] Failed to initialize service client: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise RuntimeError(f"[Database] Service client init failed: {e}") from e


async def get_anon_client() -> AsyncClient:
    """
    Return the async Supabase anon client (singleton).

    Respects RLS — used for all user-facing API routes.

    USE FOR: routes/feed.py, routes/news.py
    NEVER FOR: pipeline internals
    """
    global _anon_client

    if _anon_client is not None:
        return _anon_client

    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        raise RuntimeError(
            "[Database] SUPABASE_URL or SUPABASE_ANON_KEY not set."
        )

    try:
        _anon_client = await create_async_client(
            supabase_url=config.SUPABASE_URL,
            supabase_key=config.SUPABASE_ANON_KEY,
        )
        logger.info("[Database] Async anon client initialized.")
        return _anon_client

    except Exception as e:
        logger.error(
            f"[Database] Failed to initialize anon client: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise RuntimeError(f"[Database] Anon client init failed: {e}") from e


async def reset_clients() -> None:
    """Reset singletons — test use only."""
    global _service_client, _anon_client
    _service_client = None
    _anon_client = None
    logger.debug("[Database] Clients reset (test use only).")
# radar/scrapers/base.py
#
# Abstract base class for all Research Radar scrapers.
# Provides: shared httpx.AsyncClient, retry-on-network-error, fetch_url().
# All scrapers (arXiv, HuggingFace, RSS blogs) inherit from this.

import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger("paperlens.radar.scrapers")

# ---------------------------------------------------------------------------
# Only retry on TRUE network failures — not on HTTP 4xx/5xx responses
# ---------------------------------------------------------------------------
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

SERVER_ERROR_CODES = {429, 500, 502, 503, 504}


class BaseScraper(ABC):
    """
    Abstract base for all Radar scrapers.

    Provides:
      - Shared httpx.AsyncClient (connection pooling — one client per instance)
      - Retry decorator wrapping only the network call (not status-code logic)
      - fetch_url(): safe HTTP GET that returns text or None
      - close(): graceful shutdown called by the scheduler

    Child classes implement scrape() → list[dict] of content items.
    """

    def __init__(self, source_name: str):
        self.source_name = source_name

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
            follow_redirects=True,
        )
        logger.info(f"[{self.source_name}] Scraper initialized.")

    # -------------------------------------------------------------------------
    # Internal retry-decorated raw fetch — called only by fetch_url()
    # -------------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_with_retry(
        self, url: str, headers: Optional[dict] = None
    ) -> httpx.Response:
        logger.debug(f"[{self.source_name}] GET {url}")
        return await self.client.get(url, headers=headers or {})

    # -------------------------------------------------------------------------
    # Public fetch — returns text string or None on any failure
    # -------------------------------------------------------------------------
    async def fetch_url(
        self, url: str, headers: Optional[dict] = None
    ) -> Optional[str]:
        """
        Safely fetch a URL. Returns response text or None.

        Handles:
          - Network errors after 3 retries → None
          - 429 / 5xx server errors → None (retry on next cycle)
          - 401 / 403 auth errors → None (log clearly for debugging)
          - 404 not found → None (silent)
          - 200 → response text
        """
        try:
            response = await self._fetch_with_retry(url, headers=headers)

            if response.status_code == 200:
                return response.text

            if response.status_code in SERVER_ERROR_CODES:
                logger.warning(
                    f"[{self.source_name}] HTTP {response.status_code} from {url}. "
                    f"Will retry next cycle."
                )
                return None

            if response.status_code in (401, 403):
                logger.warning(
                    f"[{self.source_name}] HTTP {response.status_code} (auth) from {url}. "
                    f"Check API keys."
                )
                return None

            if response.status_code == 404:
                logger.info(f"[{self.source_name}] HTTP 404 — not found: {url}")
                return None

            logger.warning(
                f"[{self.source_name}] Unexpected HTTP {response.status_code} from {url}."
            )
            return None

        except RETRYABLE_EXCEPTIONS as e:
            logger.warning(
                f"[{self.source_name}] Network error after retries for {url}: "
                f"{type(e).__name__}: {e}"
            )
            return None

        except Exception as e:
            logger.error(
                f"[{self.source_name}] Unexpected error fetching {url}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return None

    @abstractmethod
    async def scrape(self) -> list[dict]:
        """
        Main entry point. Must return list of content item dicts.
        Each dict must have: title, source_url, source_name, content_type.
        Never raises — returns [] on any failure.
        """
        pass

    async def close(self) -> None:
        """Close shared HTTP client. Called by scheduler on shutdown."""
        await self.client.aclose()
        logger.info(f"[{self.source_name}] HTTP client closed.")

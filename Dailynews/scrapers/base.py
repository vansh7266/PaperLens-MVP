# scrapers/base.py

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

# Module-level logger — never use logging.basicConfig here
# Root config is handled in main.py only
logger = logging.getLogger("paperlens.scrapers")

# ---------------------------------------------------------------------------
# Retry only on TRUE network failures (server was unreachable / dropped conn)
# HTTP 4xx/5xx are NOT exceptions — they're valid responses we handle manually
# ---------------------------------------------------------------------------
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,        # Could not connect to server
    httpx.ReadError,           # Connection dropped while reading
    httpx.TimeoutException,    # Request timed out
    httpx.NetworkError,        # General network failure
    httpx.RemoteProtocolError, # Server sent malformed response
)

# HTTP status codes that indicate temporary server-side errors
# We skip these and retry on the next scheduler cycle (30 min later)
SERVER_ERROR_CODES = {429, 500, 502, 503, 504}


class BaseScraper(ABC):
    """
    Abstract base class for all PaperLens scrapers.

    All scrapers (arXiv, HuggingFace, RSS blogs) inherit from this class.
    It provides:
      - A shared httpx.AsyncClient (connection pooling — one client per scraper instance)
      - A retry decorator for network-level failures only
      - fetch_url(): the standard method to make HTTP GET requests safely
      - close(): graceful shutdown of the HTTP client

    Child classes must implement scrape() — the main entry point
    that returns a list of content items ready for the processor.
    """

    def __init__(self, source_name: str):
        """
        Initialize the scraper with a shared HTTP client.

        Args:
            source_name: Human-readable name for this scraper (e.g. "arXiv", "HuggingFace")
                         Used in log messages so we know which scraper is talking.
        """
        self.source_name = source_name

        # ONE client created here, reused for EVERY request this scraper makes.
        # This is connection pooling — avoids the overhead of TCP handshake per request.
        # limits= controls how many simultaneous connections we allow.
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,   # Max seconds to establish connection
                read=30.0,      # Max seconds to wait for server to send data
                write=10.0,     # Max seconds to send our request
                pool=5.0,       # Max seconds to wait for a free connection from pool
            ),
            limits=httpx.Limits(
                max_connections=10,        # Total simultaneous connections
                max_keepalive_connections=5,  # Persistent connections kept alive
            ),
            # Follow redirects automatically (arXiv and some blogs redirect HTTP→HTTPS)
            follow_redirects=True,
        )

        logger.info(f"[{self.source_name}] Scraper initialized with shared HTTP client.")

    # -----------------------------------------------------------------------
    # Internal retry-decorated fetch — only retries on NETWORK exceptions.
    # NOT called directly by child classes — they call fetch_url() instead.
    # -----------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),  # Only retry on network errors
        stop=stop_after_attempt(3),           # Max 3 attempts total (1 original + 2 retries)
        wait=wait_exponential(multiplier=1, min=2, max=10),  # Wait 2s, 4s, 8s... between retries
        reraise=True,  # Re-raises original exception (caught by except RETRYABLE_EXCEPTIONS below)
    )
    async def _fetch_with_retry(self, url: str, headers: Optional[dict] = None) -> httpx.Response:
        """
        Internal method: makes the actual HTTP GET request with retry on network errors.

        This is separated from fetch_url() so that tenacity wraps ONLY the network call,
        not our status-code handling logic below.

        Args:
            url: The URL to fetch
            headers: Optional dict of extra HTTP headers (e.g. Authorization for HuggingFace)

        Returns:
            httpx.Response object (caller checks .status_code)

        Raises:
            RETRYABLE_EXCEPTIONS: After all retries exhausted (caught in fetch_url)
        """
        logger.debug(f"[{self.source_name}] GET {url}")
        # self.client is the shared AsyncClient — no new client created here
        response = await self.client.get(url, headers=headers or {})
        return response

    async def fetch_url(self, url: str, headers: Optional[dict] = None) -> Optional[str]:
        """
        Public method for child scrapers to fetch a URL safely.

        Handles:
          - Network errors (after retries): logs warning, returns None
          - 429 / 5xx (server errors): logs warning, returns None
            (scheduler will retry on next 30-min cycle — no need to crash)
          - 404 / 401: logs info (expected sometimes), returns None
          - 200: returns response text (HTML/XML/JSON as string)

        Args:
            url: The URL to fetch
            headers: Optional extra headers (e.g. {"Authorization": "Bearer <token>"})

        Returns:
            Response body as string if successful, None otherwise.
            Child scrapers must handle None and return [] from scrape().
        """
        try:
            response = await self._fetch_with_retry(url, headers=headers)

            # --- Handle HTTP status codes manually ---

            if response.status_code == 200:
                # All good — return the raw text (XML, JSON, or HTML)
                return response.text

            elif response.status_code in SERVER_ERROR_CODES:
                # Server-side error or rate limit — we don't crash, just skip this cycle
                logger.warning(
                    f"[{self.source_name}] HTTP {response.status_code} from {url}. "
                    f"Will retry on next scheduler cycle."
                )
                return None

            elif response.status_code in (401, 403):
                # Auth issue — log clearly so developer notices (wrong API key etc.)
                logger.warning(
                    f"[{self.source_name}] HTTP {response.status_code} (auth error) from {url}. "
                    f"Check API keys."
                )
                return None

            elif response.status_code == 404:
                # Resource not found — not our fault, just skip silently
                logger.info(f"[{self.source_name}] HTTP 404 — resource not found: {url}")
                return None

            else:
                # Any other unexpected status — log and move on
                logger.warning(
                    f"[{self.source_name}] Unexpected HTTP {response.status_code} from {url}."
                )
                return None

        except RETRYABLE_EXCEPTIONS as e:
            # Network failed even after all retries — don't crash, just skip this cycle
            logger.warning(
                f"[{self.source_name}] Network error after retries for {url}: {type(e).__name__}: {e}"
            )
            return None

        except Exception as e:
            # Catch-all: unexpected error (e.g. SSL cert issue, DNS failure)
            # Never let an unexpected exception propagate up and crash the scheduler
            logger.error(
                f"[{self.source_name}] Unexpected error fetching {url}: {type(e).__name__}: {e}",
                exc_info=True,  # Includes full traceback in logs
            )
            return None

    @abstractmethod
    async def scrape(self) -> list[dict]:
        """
        Main entry point for each scraper. Must be implemented by every child class.

        Returns:
            List of dicts, each representing one content item.
            Each dict must have at minimum: title, source_url, source_name, content_type.
            Returns [] (empty list) on any failure — never raises.
        """
        pass

    async def close(self) -> None:
        """
        Gracefully close the shared HTTP client.

        Called by the scheduler on shutdown so connections are released cleanly.
        Without this, the event loop may log "Unclosed client session" warnings.
        """
        await self.client.aclose()
        logger.info(f"[{self.source_name}] HTTP client closed.")
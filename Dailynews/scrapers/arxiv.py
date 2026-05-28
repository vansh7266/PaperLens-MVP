# scrapers/arxiv.py

import asyncio
import logging
import re
import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse

import feedparser

from scrapers.base import BaseScraper

# Module-level logger — no basicConfig here
logger = logging.getLogger("paperlens.scrapers.arxiv")

# ---------------------------------------------------------------------------
# arXiv RSS feed URLs — one per category we track
# These return the latest ~20 papers per category in RSS/XML format
# ---------------------------------------------------------------------------
ARXIV_RSS_FEEDS = {
    "cs.AI": "https://rss.arxiv.org/rss/cs.AI",
    "cs.LG": "https://rss.arxiv.org/rss/cs.LG",
    "cs.CV": "https://rss.arxiv.org/rss/cs.CV",
    "cs.CL": "https://rss.arxiv.org/rss/cs.CL",
    "stat.ML": "https://rss.arxiv.org/rss/stat.ML",
}

# Regex to detect and strip version suffix from arXiv IDs
# e.g. "2301.00001v2" → "2301.00001"
# e.g. "2301.00001v12" → "2301.00001"
ARXIV_VERSION_PATTERN = re.compile(r"v\d+$")


class ArxivScraper(BaseScraper):
    """
    Scraper for arXiv research papers via RSS feeds.

    Fetches papers from 5 categories in parallel, normalizes IDs and URLs,
    deduplicates across categories, and returns a unified list of dicts
    ready for pipeline/processor.py.

    Inherits fetch_url(), retry logic, and connection pooling from BaseScraper.
    """

    def __init__(self):
        """Initialize with source name passed to BaseScraper."""
        super().__init__(source_name="arXiv")

    # -----------------------------------------------------------------------
    # ID + URL normalization helpers
    # -----------------------------------------------------------------------

    def _normalize_arxiv_id(self, raw_id: str) -> str:
        """
        Strip version suffix from arXiv ID.

        arXiv appends v1, v2, v3 etc. when papers are updated.
        We treat all versions as the same paper — deduplicate on base ID.

        Example:
            "2301.00001v2"  → "2301.00001"
            "2301.00001v12" → "2301.00001"
            "2301.00001"    → "2301.00001"  (no change)

        Args:
            raw_id: arXiv ID string, possibly with version suffix

        Returns:
            Clean arXiv ID without version suffix
        """
        return ARXIV_VERSION_PATTERN.sub("", raw_id.strip())

    def _normalize_url(self, raw_url: str) -> str:
        """
        Strip query parameters from a URL.

        Prevents duplicate entries caused by tracking params like ?utm_source=feedburner.
        We only keep scheme + netloc + path — the canonical URL.

        Example:
            "https://arxiv.org/abs/2301.00001?utm_source=rss" → "https://arxiv.org/abs/2301.00001"

        Args:
            raw_url: URL string, possibly with query params

        Returns:
            Clean URL with no query string or fragment
        """
        parsed = urlparse(raw_url)
        scheme = "https" if parsed.scheme == "http" else parsed.scheme
        clean = urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))
        return clean.strip()

    def _extract_arxiv_id_from_url(self, url: str) -> Optional[str]:
        """
        Extract arXiv ID from an abstract URL.

        arXiv abstract URLs follow the pattern:
            https://arxiv.org/abs/2301.00001

        Args:
            url: Normalized arXiv abstract URL

        Returns:
            arXiv ID string (e.g. "2301.00001"), or None if pattern doesn't match
        """
        # Match the ID portion after /abs/
        match = re.search(r"arxiv\.org/abs/([^\s/]+)", url)
        if match:
            return self._normalize_arxiv_id(match.group(1))
        return None

    # -----------------------------------------------------------------------
    # RSS parsing (runs in thread — feedparser is blocking I/O)
    # -----------------------------------------------------------------------

    async def _parse_feed(self, raw_xml: str) -> list:
        """
        Parse RSS/XML string using feedparser, safely in a thread.

        feedparser.parse() is a BLOCKING call — it reads and parses the entire
        XML string synchronously. Running it directly in async would block the
        event loop. asyncio.to_thread() moves it to a thread pool so other
        coroutines can run while parsing happens.

        Args:
            raw_xml: Raw RSS/XML string returned by fetch_url()

        Returns:
            List of feedparser entry objects (each is a parsed paper)
            Returns [] if parsing fails or feed has no entries
        """
        try:
            # Run blocking feedparser.parse() in a thread pool
            feed = await asyncio.to_thread(feedparser.parse, raw_xml)

            # feedparser sets bozo=True if the XML was malformed
            if feed.bozo:
                logger.warning(
                    f"[{self.source_name}] Malformed RSS feed XML: {feed.bozo_exception}"
                )
                # Still try to use entries — feedparser is lenient and often recovers

            return feed.entries or []

        except Exception as e:
            logger.error(
                f"[{self.source_name}] Failed to parse RSS feed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

    # -----------------------------------------------------------------------
    # Per-category scrape (fetches + parses one RSS feed)
    # -----------------------------------------------------------------------

    async def _scrape_category(self, category: str, feed_url: str) -> list[dict]:
        """
        Fetch and parse one arXiv RSS category feed.

        Steps:
          1. fetch_url() → raw XML string (or None on failure)
          2. _parse_feed() → list of feedparser entries
          3. Loop entries → extract + normalize fields → build dict

        Args:
            category: arXiv category string e.g. "cs.AI"
            feed_url: RSS URL for this category

        Returns:
            List of content item dicts for this category.
            Returns [] on any failure — never raises.
        """
        logger.info(f"[{self.source_name}] Fetching category: {category}")

        # Step 1: Fetch raw RSS XML using BaseScraper's safe fetch method
        raw_xml = await self.fetch_url(feed_url)

        if raw_xml is None:
            # fetch_url already logged the error — just return empty
            logger.warning(f"[{self.source_name}] Skipping {category} — fetch returned None.")
            return []

        # Step 2: Parse RSS XML into feedparser entries
        entries = await self._parse_feed(raw_xml)

        if not entries:
            logger.info(f"[{self.source_name}] No entries found for {category}.")
            return []

        # Step 3: Convert feedparser entries to our content_items schema
        items = []
        for entry in entries:
            try:
                # --- Extract raw fields from feedparser entry ---

                raw_title = entry.get("title", "").strip()
                raw_url = entry.get("link", "").strip()

                # Skip entries missing critical fields
                if not raw_title or not raw_url:
                    logger.debug(f"[{self.source_name}] Skipping entry with missing title/URL.")
                    continue

                # --- Normalize URL and extract arXiv ID ---

                source_url = self._normalize_url(raw_url)
                arxiv_id = self._extract_arxiv_id_from_url(source_url)

                # --- Extract authors ---
                # feedparser gives authors as a list of dicts: [{"name": "Alice"}, ...]
                authors_list = entry.get("authors", [])
                authors = [a.get("name", "").strip() for a in authors_list if a.get("name")]

                # --- Extract abstract (summary field in RSS) ---
                # arXiv RSS puts the abstract in entry.summary
                # Strip HTML tags if present (arXiv sometimes wraps in <p>)
                raw_summary = entry.get("summary", "").strip()
                abstract = re.sub(r"<[^>]+>", "", raw_summary).strip()

                # --- Published date ---
                # feedparser parses this into a time.struct_time in entry.published_parsed
                # We keep it as ISO string for Supabase
                published_at = None
                if entry.get("published_parsed"):
                    # published_parsed is a time.struct_time tuple
                    published_at = datetime.datetime(*entry.published_parsed[:6]).isoformat()

                # --- Build content item dict matching content_items schema ---
                item = {
                    "title": raw_title,
                    "source_url": source_url,       # UNIQUE key for deduplication in DB
                    "source_name": "arXiv",
                    "content_type": "paper",        # Always "paper" for arXiv
                    "arxiv_id": arxiv_id,           # Normalized, used for dedup + linking
                    "authors": authors,
                    "full_content": abstract,       # Abstract stored as full_content
                    "published_at": published_at,
                    "metadata_json": {
                        "category": category,       # e.g. "cs.AI" — useful for filtering later
                    },
                    # Fields set by processor — not scrapers
                    "topic": None,
                    "difficulty": None,
                    "attention_score": None,
                    "is_summarized": False,
                    "is_released": False,
                }

                items.append(item)

            except Exception as e:
                # Never let one bad entry crash the whole category fetch
                logger.error(
                    f"[{self.source_name}] Error processing entry in {category}: "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue  # Move to next entry

        logger.info(f"[{self.source_name}] {category}: {len(items)} papers scraped.")
        return items

    # -----------------------------------------------------------------------
    # Main scrape() — runs all categories in parallel
    # -----------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Scrape all arXiv RSS categories in parallel and return deduplicated results.

        Runs all 5 category fetches simultaneously using asyncio.gather().
        Deduplicates by source_url — same paper can appear in multiple categories
        (e.g. a paper on LLMs might be in both cs.AI and cs.CL).

        Returns:
            List of unique content item dicts, ready for pipeline/processor.py.
            Returns [] if all categories fail — never raises.
        """
        logger.info(f"[{self.source_name}] Starting parallel scrape of {len(ARXIV_RSS_FEEDS)} categories.")

        # Run all category scrapes simultaneously
        # return_exceptions=True means one failing category doesn't cancel others
        results = await asyncio.gather(
            *[
                self._scrape_category(category, url)
                for category, url in ARXIV_RSS_FEEDS.items()
            ],
            return_exceptions=True,
        )

        # Flatten results + handle any unexpected exceptions from gather
        all_items = []
        for category, result in zip(ARXIV_RSS_FEEDS.keys(), results):
            if isinstance(result, Exception):
                # Unexpected exception from a category — log and skip
                logger.error(
                    f"[{self.source_name}] Unhandled exception in {category}: "
                    f"{type(result).__name__}: {result}"
                )
            else:
                all_items.extend(result)

        # Deduplicate by source_url (same paper across multiple categories)
        seen_urls = set()
        unique_items = []
        for item in all_items:
            url = item["source_url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique_items.append(item)

        logger.info(
            f"[{self.source_name}] Scrape complete. "
            f"{len(all_items)} total → {len(unique_items)} unique papers."
        )

        return unique_items
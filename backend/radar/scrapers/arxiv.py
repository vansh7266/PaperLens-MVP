# radar/scrapers/arxiv.py
#
# arXiv RSS scraper — fetches latest papers from 5 categories in parallel.
# Each category returns ~20 papers. Cross-category duplicates are removed.

import asyncio
import datetime
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

import feedparser

from radar.scrapers.base import BaseScraper

logger = logging.getLogger("paperlens.radar.scrapers.arxiv")

# arXiv RSS feed URLs — one per AI/ML category we track
ARXIV_RSS_FEEDS = {
    "cs.AI":   "https://rss.arxiv.org/rss/cs.AI",
    "cs.LG":   "https://rss.arxiv.org/rss/cs.LG",
    "cs.CV":   "https://rss.arxiv.org/rss/cs.CV",
    "cs.CL":   "https://rss.arxiv.org/rss/cs.CL",
    "stat.ML": "https://rss.arxiv.org/rss/stat.ML",
}

# Strip version suffix: "2301.00001v2" → "2301.00001"
ARXIV_VERSION_RE = re.compile(r"v\d+$")


class ArxivScraper(BaseScraper):
    """
    Fetches arXiv papers from 5 RSS categories in parallel.
    Deduplicates by both source_url and arxiv_id (same paper across categories).
    Returns list of content item dicts ready for the processor.
    """

    def __init__(self):
        super().__init__(source_name="arXiv")

    # -------------------------------------------------------------------------
    # Normalization helpers
    # -------------------------------------------------------------------------

    def _normalize_arxiv_id(self, raw_id: str) -> str:
        """Strip version suffix: '2301.00001v2' → '2301.00001'."""
        return ARXIV_VERSION_RE.sub("", raw_id.strip())

    def _normalize_url(self, raw_url: str) -> str:
        """Strip query params and force HTTPS: removes ?utm_source etc."""
        parsed = urlparse(raw_url)
        scheme = "https" if parsed.scheme == "http" else parsed.scheme
        return urlunparse((scheme, parsed.netloc, parsed.path, "", "", "")).strip()

    def _extract_arxiv_id(self, url: str) -> Optional[str]:
        """Extract arXiv ID from URL: 'https://arxiv.org/abs/2301.00001' → '2301.00001'."""
        match = re.search(r"arxiv\.org/abs/([^\s/]+)", url)
        if match:
            return self._normalize_arxiv_id(match.group(1))
        return None

    # -------------------------------------------------------------------------
    # RSS parsing (blocking — runs in thread pool)
    # -------------------------------------------------------------------------

    async def _parse_feed(self, raw_xml: str) -> list:
        """Parse RSS XML using feedparser in a thread (feedparser is blocking)."""
        try:
            feed = await asyncio.to_thread(feedparser.parse, raw_xml)
            if feed.bozo:
                logger.warning(
                    f"[arXiv] Malformed RSS feed XML: {feed.bozo_exception}"
                )
            return feed.entries or []
        except Exception as e:
            logger.error(
                f"[arXiv] Failed to parse RSS feed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

    # -------------------------------------------------------------------------
    # Per-category scrape
    # -------------------------------------------------------------------------

    async def _scrape_category(self, category: str, feed_url: str) -> list[dict]:
        """Fetch and parse one arXiv RSS category. Returns [] on any failure."""
        logger.info(f"[arXiv] Fetching category: {category}")

        raw_xml = await self.fetch_url(feed_url)
        if raw_xml is None:
            return []

        entries = await self._parse_feed(raw_xml)
        if not entries:
            return []

        items = []
        for entry in entries:
            try:
                raw_title = entry.get("title", "").strip()
                raw_url   = entry.get("link", "").strip()

                if not raw_title or not raw_url:
                    continue

                source_url = self._normalize_url(raw_url)
                arxiv_id   = self._extract_arxiv_id(source_url)

                # Authors: feedparser gives [{"name": "Alice"}, ...]
                authors = [
                    a.get("name", "").strip()
                    for a in entry.get("authors", [])
                    if a.get("name")
                ]

                # Abstract: strip HTML tags
                raw_summary = entry.get("summary", "").strip()
                abstract    = re.sub(r"<[^>]+>", "", raw_summary).strip()

                # Published date → ISO string
                published_at = None
                if entry.get("published_parsed"):
                    published_at = datetime.datetime(
                        *entry.published_parsed[:6]
                    ).isoformat()

                items.append({
                    "title":        raw_title,
                    "source_url":   source_url,
                    "source_name":  "arXiv",
                    "content_type": "paper",
                    "arxiv_id":     arxiv_id,
                    "authors":      authors,
                    "full_content": abstract,
                    "published_at": published_at,
                    "metadata_json": {"category": category},
                    # Processor fills these:
                    "topic":            None,
                    "difficulty":       None,
                    "attention_score":  None,
                    "is_summarized":    False,
                    "is_released":      False,
                })

            except Exception as e:
                logger.error(
                    f"[arXiv] Error processing entry in {category}: "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue

        logger.info(f"[arXiv] {category}: {len(items)} papers scraped.")
        return items

    # -------------------------------------------------------------------------
    # Main scrape() — all categories in parallel
    # -------------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Scrape all arXiv RSS categories in parallel.
        Deduplicates by source_url across categories.
        Returns [] if all categories fail.
        """
        logger.info(f"[arXiv] Starting parallel scrape of {len(ARXIV_RSS_FEEDS)} categories.")

        results = await asyncio.gather(
            *[self._scrape_category(cat, url) for cat, url in ARXIV_RSS_FEEDS.items()],
            return_exceptions=True,
        )

        all_items = []
        for category, result in zip(ARXIV_RSS_FEEDS.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"[arXiv] Exception in {category}: {type(result).__name__}: {result}")
            else:
                all_items.extend(result)

        # Deduplicate by source_url (same paper in multiple categories)
        seen_urls = set()
        unique = []
        for item in all_items:
            url = item["source_url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(item)

        logger.info(
            f"[arXiv] Scrape done. {len(all_items)} total → {len(unique)} unique papers."
        )
        return unique

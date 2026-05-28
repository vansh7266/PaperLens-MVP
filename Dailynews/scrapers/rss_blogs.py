# scrapers/rss_blogs.py

import asyncio
import datetime
import logging
import re
from urllib.parse import urlparse, urlunparse

import feedparser

from scrapers.base import BaseScraper

logger = logging.getLogger("paperlens.scrapers.rss_blogs")

# ---------------------------------------------------------------------------
# Company blog RSS feeds — (source_name, rss_url) pairs
# source_name becomes the source_name field in content_items
# These URLs are verified working RSS endpoints as of build time
# ---------------------------------------------------------------------------
BLOG_RSS_FEEDS = {
    "Anthropic":    "https://www.anthropic.com/rss.xml",
    "OpenAI":       "https://openai.com/blog/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Meta AI":      "https://ai.meta.com/blog/rss/",
    "Mistral AI":   "https://mistral.ai/news/rss.xml",
}

# Regex to strip any HTML tags from blog summaries
# e.g. "<p>Hello <b>world</b></p>" → "Hello world"
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# Regex to collapse multiple whitespace/newlines into single space
WHITESPACE_PATTERN = re.compile(r"\s+")


class RSSBlogScraper(BaseScraper):
    """
    Scraper for AI company blog posts via RSS feeds.

    Fetches from 5 company blogs in parallel:
    Anthropic, OpenAI, Google DeepMind, Meta AI, Mistral AI.

    Each blog produces items with:
      - content_type = "blog_post"
      - source_name  = company name (e.g. "Anthropic")
      - full_content = cleaned plain-text summary from RSS

    Inherits fetch_url(), retry logic, and connection pooling from BaseScraper.
    """

    def __init__(self):
        """Initialize with source name for BaseScraper logging."""
        super().__init__(source_name="RSSBlogs")

    # -----------------------------------------------------------------------
    # URL normalization (same pattern as arxiv.py — strip query, force HTTPS)
    # -----------------------------------------------------------------------

    def _normalize_url(self, raw_url: str) -> str:
        """
        Strip query parameters and force HTTPS on a URL.

        Blog RSS feeds often include tracking params like ?utm_source=rss.
        We strip these so deduplication works correctly in the DB.

        Args:
            raw_url: URL string from feedparser entry

        Returns:
            Clean HTTPS URL with no query string or fragment
        """
        parsed = urlparse(raw_url.strip())

        # Force HTTPS — some feeds return HTTP links
        scheme = "https" if parsed.scheme == "http" else parsed.scheme

        # Reconstruct with scheme + netloc + path only
        clean = urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))
        return clean

    # -----------------------------------------------------------------------
    # HTML cleaning for blog summaries
    # -----------------------------------------------------------------------

    def _clean_html(self, raw_text: str) -> str:
        """
        Strip HTML tags and clean whitespace from a blog summary.

        Blog RSS feeds often include raw HTML in the <description> field:
          "<p>We introduce <b>Claude 3</b>, our...</p>"

        We want plain text for storage and display:
          "We introduce Claude 3, our..."

        Args:
            raw_text: Raw summary string, possibly containing HTML

        Returns:
            Clean plain-text string, or "" if input is empty
        """
        if not raw_text:
            return ""

        # Step 1: Strip all HTML tags
        text = HTML_TAG_PATTERN.sub(" ", raw_text)

        # Step 2: Collapse multiple spaces/newlines into single space
        text = WHITESPACE_PATTERN.sub(" ", text)

        # Step 3: Strip leading/trailing whitespace
        return text.strip()

    # -----------------------------------------------------------------------
    # Date parsing (same pattern as arxiv.py)
    # -----------------------------------------------------------------------

    def _parse_published_date(self, entry) -> str | None:
        """
        Extract and convert feedparser's published_parsed to ISO 8601 string.

        feedparser parses RSS date strings into time.struct_time objects stored
        in entry.published_parsed. We convert to ISO 8601 for PostgreSQL.

        Args:
            entry: feedparser entry object

        Returns:
            ISO 8601 datetime string (e.g. "2024-01-15T10:30:00"), or None
        """
        if entry.get("published_parsed"):
            try:
                # published_parsed is a time.struct_time — first 6 values are
                # (year, month, day, hour, minute, second)
                return datetime.datetime(*entry.published_parsed[:6]).isoformat()
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"[{self.source_name}] Could not parse published_parsed: {e}"
                )

        # Fallback: try updated_parsed (some feeds use this instead of published)
        if entry.get("updated_parsed"):
            try:
                return datetime.datetime(*entry.updated_parsed[:6]).isoformat()
            except (TypeError, ValueError):
                pass

        return None

    # -----------------------------------------------------------------------
    # Per-blog scrape
    # -----------------------------------------------------------------------

    async def _scrape_blog(self, blog_name: str, feed_url: str) -> list[dict]:
        """
        Fetch and parse one company blog RSS feed.

        Steps:
          1. fetch_url() → raw RSS/XML string (or None on failure)
          2. feedparser.parse() in asyncio.to_thread() → list of entries
          3. Convert each entry → content_items schema dict

        Args:
            blog_name: Human-readable company name (e.g. "Anthropic")
                       Used as source_name in content_items
            feed_url:  RSS feed URL for this blog

        Returns:
            List of content item dicts for this blog.
            Returns [] on any failure — never raises.
        """
        logger.info(f"[{self.source_name}] Fetching blog: {blog_name}")

        # Step 1: Fetch raw RSS XML
        raw_xml = await self.fetch_url(feed_url)

        if raw_xml is None:
            # fetch_url already logged the error — skip this blog
            logger.warning(f"[{self.source_name}] Skipping {blog_name} — fetch returned None.")
            return []

        # Step 2: Parse RSS in a thread (feedparser is blocking)
        try:
            feed = await asyncio.to_thread(feedparser.parse, raw_xml)

            if feed.bozo:
                # bozo=True means malformed XML — log but still try to use entries
                logger.warning(
                    f"[{self.source_name}] Malformed RSS from {blog_name}: "
                    f"{feed.bozo_exception}"
                )

            entries = feed.entries or []

        except Exception as e:
            logger.error(
                f"[{self.source_name}] feedparser failed for {blog_name}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

        if not entries:
            logger.info(f"[{self.source_name}] No entries found for {blog_name}.")
            return []

        # Step 3: Convert entries to content_items schema
        items = []
        for entry in entries:
            try:
                # --- Extract and validate required fields ---
                raw_title = entry.get("title", "").strip()
                raw_url = entry.get("link", "").strip()

                # Skip entries missing critical fields
                if not raw_title or not raw_url:
                    logger.debug(
                        f"[{self.source_name}] Skipping {blog_name} entry "
                        f"with missing title or URL."
                    )
                    continue

                # --- Normalize URL ---
                source_url = self._normalize_url(raw_url)

                # --- Extract and clean summary ---
                # feedparser checks: entry.summary → entry.description → ""
                # Some blogs put HTML in summary, others use plain text
                raw_summary = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )
                full_content = self._clean_html(raw_summary)

                # --- Extract published date ---
                published_at = self._parse_published_date(entry)

                # --- Extract authors ---
                # Blog RSS sometimes has author field, sometimes not
                # Return as list to match TEXT[] schema
                authors_raw = entry.get("authors", [])
                if authors_raw:
                    authors = [
                        a.get("name", "").strip()
                        for a in authors_raw
                        if a.get("name")
                    ]
                else:
                    # Fallback: some feeds have a flat "author" string field
                    single_author = entry.get("author", "").strip()
                    authors = [single_author] if single_author else []

                # --- Build content item dict matching content_items schema ---
                item = {
                    "title": raw_title,
                    "source_url": source_url,       # UNIQUE — deduplication key in DB
                    "source_name": blog_name,        # e.g. "Anthropic", "OpenAI"
                    "content_type": "blog_post",     # Always "blog_post" for RSS blogs
                    "arxiv_id": None,                # Blog posts have no arXiv ID
                    "authors": authors,              # List — matches TEXT[] schema
                    "full_content": full_content,    # Plain-text summary
                    "published_at": published_at,    # ISO 8601 or None
                    "metadata_json": {
                        "feed_url": feed_url,        # Original RSS feed URL — useful for debugging
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
                # Never let one bad entry crash the whole blog scrape
                logger.error(
                    f"[{self.source_name}] Error processing entry from {blog_name}: "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue

        logger.info(f"[{self.source_name}] {blog_name}: {len(items)} posts scraped.")
        return items

    # -----------------------------------------------------------------------
    # Main scrape() — all blogs in parallel
    # -----------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Scrape all company blog RSS feeds in parallel and return deduplicated results.

        Runs all blog fetches simultaneously using asyncio.gather().
        One blog failing (404, timeout, bad RSS) does not affect the others.
        Deduplicates by source_url — unlikely across blogs but possible if
        a post is cross-posted or syndicated.

        Returns:
            List of unique content item dicts ready for pipeline/processor.py.
            Returns [] if all blogs fail — never raises.
        """
        logger.info(
            f"[{self.source_name}] Starting parallel scrape of "
            f"{len(BLOG_RSS_FEEDS)} company blogs."
        )

        # Run all blog scrapes simultaneously
        # return_exceptions=True — one failing blog doesn't cancel others
        results = await asyncio.gather(
            *[
                self._scrape_blog(name, url)
                for name, url in BLOG_RSS_FEEDS.items()
            ],
            return_exceptions=True,
        )

        # Flatten results + handle unexpected exceptions from gather
        all_items = []
        for blog_name, result in zip(BLOG_RSS_FEEDS.keys(), results):
            if isinstance(result, Exception):
                logger.error(
                    f"[{self.source_name}] Unhandled exception scraping {blog_name}: "
                    f"{type(result).__name__}: {result}"
                )
            else:
                all_items.extend(result)

        # Deduplicate by source_url across all blogs
        seen_urls = set()
        unique_items = []
        for item in all_items:
            url = item["source_url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique_items.append(item)

        logger.info(
            f"[{self.source_name}] Scrape complete. "
            f"{len(all_items)} total → {len(unique_items)} unique blog posts."
        )

        return unique_items
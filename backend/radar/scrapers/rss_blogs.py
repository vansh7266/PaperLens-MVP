# radar/scrapers/rss_blogs.py
#
# Company blog RSS scraper — fetches posts from major AI labs in parallel.
# Produces content_type="blog_post" items for the Company Updates feed.

import asyncio
import datetime
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

import feedparser

from radar.scrapers.base import BaseScraper

logger = logging.getLogger("paperlens.radar.scrapers.rss_blogs")

# Company blog RSS feeds — (source_name, rss_url) pairs
# source_name becomes the source_name in content_items
BLOG_RSS_FEEDS = {
    "Anthropic":       "https://www.anthropic.com/rss.xml",
    "OpenAI":          "https://openai.com/blog/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Meta AI":         "https://ai.meta.com/blog/rss/",
    "Mistral AI":      "https://mistral.ai/news/rss.xml",
    "Google AI":       "https://blog.google/technology/ai/rss/",
}

HTML_TAG_RE  = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


class RSSBlogScraper(BaseScraper):
    """
    Fetches company blog posts from 6 major AI labs via RSS.
    All blogs scraped in parallel. One blog failing doesn't stop others.
    Returns content_type="blog_post" items for Company Updates section.
    """

    def __init__(self):
        super().__init__(source_name="RSSBlogs")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _normalize_url(self, raw_url: str) -> str:
        """Strip query params and force HTTPS (removes ?utm_source etc.)."""
        parsed = urlparse(raw_url.strip())
        scheme = "https" if parsed.scheme == "http" else parsed.scheme
        return urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))

    def _clean_html(self, raw_text: str) -> str:
        """Strip HTML tags and collapse whitespace → plain text."""
        if not raw_text:
            return ""
        text = HTML_TAG_RE.sub(" ", raw_text)
        text = WHITESPACE_RE.sub(" ", text)
        return text.strip()

    def _parse_date(self, entry) -> Optional[str]:
        """Extract published date from feedparser entry → ISO string."""
        for field in ("published_parsed", "updated_parsed"):
            val = entry.get(field)
            if val:
                try:
                    return datetime.datetime(*val[:6]).isoformat()
                except (TypeError, ValueError):
                    continue
        return None

    # -------------------------------------------------------------------------
    # Per-blog scrape
    # -------------------------------------------------------------------------

    async def _scrape_blog(self, blog_name: str, feed_url: str) -> list[dict]:
        """Fetch and parse one company blog RSS feed. Returns [] on failure."""
        logger.info(f"[RSS] Fetching blog: {blog_name}")

        raw_xml = await self.fetch_url(feed_url)
        if raw_xml is None:
            return []

        try:
            feed = await asyncio.to_thread(feedparser.parse, raw_xml)
            if feed.bozo:
                logger.warning(f"[RSS] Malformed RSS from {blog_name}: {feed.bozo_exception}")
            entries = feed.entries or []
        except Exception as e:
            logger.error(
                f"[RSS] feedparser failed for {blog_name}: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

        if not entries:
            return []

        items = []
        for entry in entries:
            try:
                raw_title = entry.get("title", "").strip()
                raw_url   = entry.get("link", "").strip()
                if not raw_title or not raw_url:
                    continue

                source_url   = self._normalize_url(raw_url)
                full_content = self._clean_html(
                    entry.get("summary") or entry.get("description") or ""
                )
                published_at = self._parse_date(entry)

                # Authors — some feeds have it, others don't
                authors_raw = entry.get("authors", [])
                if authors_raw:
                    authors = [
                        a.get("name", "").strip()
                        for a in authors_raw if a.get("name")
                    ]
                else:
                    single = entry.get("author", "").strip()
                    authors = [single] if single else []

                items.append({
                    "title":        raw_title,
                    "source_url":   source_url,
                    "source_name":  blog_name,
                    "content_type": "blog_post",
                    "arxiv_id":     None,
                    "authors":      authors,
                    "full_content": full_content,
                    "published_at": published_at,
                    "metadata_json": {"feed_url": feed_url},
                    "topic":            None,
                    "difficulty":       None,
                    "attention_score":  None,
                    "is_summarized":    False,
                    "is_released":      False,
                })

            except Exception as e:
                logger.error(
                    f"[RSS] Error processing entry from {blog_name}: "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue

        logger.info(f"[RSS] {blog_name}: {len(items)} posts scraped.")
        return items

    # -------------------------------------------------------------------------
    # Main scrape() — all blogs in parallel
    # -------------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Scrape all company blog RSS feeds in parallel.
        Deduplicates by source_url. Returns [] if all blogs fail.
        """
        logger.info(f"[RSS] Scraping {len(BLOG_RSS_FEEDS)} company blogs in parallel.")

        results = await asyncio.gather(
            *[self._scrape_blog(name, url) for name, url in BLOG_RSS_FEEDS.items()],
            return_exceptions=True,
        )

        all_items = []
        for blog_name, result in zip(BLOG_RSS_FEEDS.keys(), results):
            if isinstance(result, Exception):
                logger.error(
                    f"[RSS] Exception scraping {blog_name}: {type(result).__name__}: {result}"
                )
            else:
                all_items.extend(result)

        # Deduplicate by source_url
        seen = set()
        unique = []
        for item in all_items:
            url = item["source_url"]
            if url not in seen:
                seen.add(url)
                unique.append(item)

        logger.info(
            f"[RSS] Done. {len(all_items)} total → {len(unique)} unique posts."
        )
        return unique


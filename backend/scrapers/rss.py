# ============================================================
# scrapers/rss.py — Blog RSS Feed Scraper
# ============================================================
# Fetches content from official AI company blogs via RSS.
# RSS = Really Simple Syndication — a standard XML format
# that every major tech company publishes for their blog.
#
# Sources:
#   Anthropic, OpenAI, Google DeepMind, Meta AI,
#   Mistral AI, HuggingFace
#
# Key differences from arXiv:
#   - These are news/announcements, NOT research papers
#   - has_peeler = False (can't peel a blog post)
#   - paper_type = "news" or "model"
#   - No abstract — just title + description
#
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import httpx
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone
from typing import Optional

from config import RSS_FEEDS, DEBUG
from scrapers.arxiv import Paper


# ============================================================
# MODEL RELEASE KEYWORDS
# ============================================================
# If a blog post title contains these → type = "model"
# Otherwise → type = "news"

MODEL_KEYWORDS = [
    "we introduce", "we release", "we present", "introducing",
    "releasing", "launching", "open-source", "open source",
    "now available", "announcing", "new model", "new version",
    "claude", "gpt", "gemini", "llama", "mistral", "flux",
    "stable diffusion", "dall-e", "sora", "gemma", "phi",
]


# ============================================================
# MAIN FUNCTION — fetch_all_blogs()
# ============================================================

async def fetch_all_blogs(max_per_source: int = 10) -> list[Paper]:
    """
    Fetch latest posts from all configured blog RSS feeds.
    Called by scheduler every 5 minutes alongside arXiv.

    Parameters:
        max_per_source → max posts to fetch per blog

    Returns:
        List of Paper objects with type="news" or "model"
    """
    all_items = []

    print(f"\n📰 Fetching blog RSS feeds ({len(RSS_FEEDS)} sources)...")

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        for source_name, rss_url in RSS_FEEDS.items():
            try:
                items = await _fetch_one_feed(
                    client,
                    source_name,
                    rss_url,
                    max_per_source,
                )
                all_items.extend(items)
                print(f"  ✅ {source_name:20} → {len(items)} posts")

                # Small delay between requests
                await asyncio.sleep(1)

            except Exception as e:
                print(f"  ❌ {source_name:20} → Error: {str(e)[:50]}")
                continue

    print(f"\n  📦 Total blog posts: {len(all_items)}\n")
    return all_items


# ============================================================
# FETCH ONE FEED
# ============================================================

async def _fetch_one_feed(
    client: httpx.AsyncClient,
    source_name: str,
    rss_url: str,
    max_results: int,
) -> list[Paper]:
    """
    Fetch and parse one RSS feed.
    Handles both RSS 2.0 and Atom feed formats.
    """
    if DEBUG:
        print(f"  [rss] Fetching: {rss_url}")

    response = await client.get(rss_url)
    response.raise_for_status()

    xml_text = response.text

    # Try RSS 2.0 format first
    items = _parse_rss2(xml_text, source_name)

    # If no items found, try Atom format
    if not items:
        items = _parse_atom(xml_text, source_name)

    return items[:max_results]


# ============================================================
# PARSE RSS 2.0 FORMAT
# ============================================================

def _parse_rss2(xml_text: str, source_name: str) -> list[Paper]:
    """
    Parse RSS 2.0 format XML.
    Most company blogs use this format.

    Structure:
    <rss>
      <channel>
        <item>
          <title>Blog Post Title</title>
          <link>https://...</link>
          <description>Post description...</description>
          <pubDate>Mon, 22 Mar 2025...</pubDate>
        </item>
      </channel>
    </rss>
    """
    papers = []

    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return papers

        for item in channel.findall("item"):
            try:
                paper = _parse_rss2_item(item, source_name)
                if paper:
                    papers.append(paper)
            except Exception as e:
                if DEBUG:
                    print(f"  [rss] Item parse error: {e}")
                continue

    except ET.ParseError:
        pass

    return papers


def _parse_rss2_item(item, source_name: str) -> Optional[Paper]:
    """Parse a single RSS 2.0 item into a Paper object."""

    # Title
    title = item.findtext("title", "").strip()
    if not title:
        return None

    # Clean HTML from title
    title = _strip_html(title)

    # URL
    url = item.findtext("link", "").strip()
    if not url:
        # Try guid as fallback
        url = item.findtext("guid", "").strip()
    if not url:
        return None

    # Description / abstract
    description = item.findtext("description", "").strip()
    description = _strip_html(description)

    # Truncate description
    if len(description) > 500:
        description = description[:497] + "..."

    # Published date
    pub_date_str = item.findtext("pubDate", "").strip()
    published_at = _parse_date(pub_date_str)

    # Generate unique ID from URL
    item_id = _url_to_id(url)

    # Detect type: news or model release
    paper_type = _detect_type(title, description)

    # Detect topic
    topic = _detect_topic(title, description, source_name)

    return Paper(
        id=item_id,
        title=title,
        abstract=description,
        authors=[source_name],
        url=url,
        published_at=published_at,
        source=source_name.lower().replace(" ", "_"),
        source_id=item_id,
        paper_type=paper_type,
        has_peeler=False,       # blog posts can't be peeled
        topic=topic,
        difficulty="Easy",      # blog posts are always "Easy"
        categories=[],
    )


# ============================================================
# PARSE ATOM FORMAT
# ============================================================

def _parse_atom(xml_text: str, source_name: str) -> list[Paper]:
    """
    Parse Atom feed format.
    Some blogs (like HuggingFace) use Atom instead of RSS 2.0.

    Structure:
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Post Title</title>
        <link href="https://..."/>
        <summary>Description...</summary>
        <published>2025-03-22T...</published>
      </entry>
    </feed>
    """
    papers = []
    ns = "http://www.w3.org/2005/Atom"

    try:
        root = ET.fromstring(xml_text)

        # Handle namespace in root tag
        entries = root.findall(f"{{{ns}}}entry")
        if not entries:
            entries = root.findall("entry")

        for entry in entries:
            try:
                paper = _parse_atom_entry(entry, source_name, ns)
                if paper:
                    papers.append(paper)
            except Exception as e:
                if DEBUG:
                    print(f"  [rss] Atom entry error: {e}")
                continue

    except ET.ParseError:
        pass

    return papers


def _parse_atom_entry(
    entry,
    source_name: str,
    ns: str,
) -> Optional[Paper]:
    """Parse a single Atom entry."""

    # Title
    title_el = entry.find(f"{{{ns}}}title") or entry.find("title")
    title = title_el.text.strip() if title_el is not None else ""
    title = _strip_html(title)
    if not title:
        return None

    # URL
    link_el = entry.find(f"{{{ns}}}link") or entry.find("link")
    if link_el is not None:
        url = link_el.get("href", "") or link_el.text or ""
    else:
        url = ""
    if not url:
        return None

    # Summary/description
    summary_el = (
        entry.find(f"{{{ns}}}summary")
        or entry.find(f"{{{ns}}}content")
        or entry.find("summary")
        or entry.find("content")
    )
    description = ""
    if summary_el is not None and summary_el.text:
        description = _strip_html(summary_el.text.strip())
    if len(description) > 500:
        description = description[:497] + "..."

    # Published date
    pub_el = (
        entry.find(f"{{{ns}}}published")
        or entry.find(f"{{{ns}}}updated")
        or entry.find("published")
        or entry.find("updated")
    )
    pub_str = pub_el.text.strip() if pub_el is not None else ""
    published_at = _parse_date(pub_str)

    item_id = _url_to_id(url)
    paper_type = _detect_type(title, description)
    topic = _detect_topic(title, description, source_name)

    return Paper(
        id=item_id,
        title=title,
        abstract=description,
        authors=[source_name],
        url=url,
        published_at=published_at,
        source=source_name.lower().replace(" ", "_"),
        source_id=item_id,
        paper_type=paper_type,
        has_peeler=False,
        topic=topic,
        difficulty="Easy",
        categories=[],
    )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _detect_type(title: str, description: str) -> str:
    """
    Detect if a blog post is a model release or general news.
    Returns "model" or "news".
    """
    text = (title + " " + description).lower()
    for kw in MODEL_KEYWORDS:
        if kw in text:
            return "model"
    return "news"


def _detect_topic(
    title: str,
    description: str,
    source_name: str,
) -> str:
    """
    Detect the topic of a blog post.
    Uses simple keyword matching.
    """
    text = (title + " " + description).lower()

    if any(w in text for w in ["language model", "llm", "gpt", "claude", "llama"]):
        return "LLMs"
    if any(w in text for w in ["image", "vision", "diffusion", "video"]):
        return "Computer Vision"
    if any(w in text for w in ["reinforcement", "agent", "reward"]):
        return "RL / Agents"
    if any(w in text for w in ["safety", "alignment", "interpretability"]):
        return "AI Safety"
    if any(w in text for w in ["multimodal", "vision-language"]):
        return "Multimodal"

    # Default based on source
    return "LLMs"


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Decode common entities
    clean = clean.replace('&amp;', '&')
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    clean = clean.replace('&quot;', '"')
    clean = clean.replace('&#39;', "'")
    clean = clean.replace('&nbsp;', ' ')
    # Clean whitespace
    clean = ' '.join(clean.split())
    return clean.strip()


def _url_to_id(url: str) -> str:
    """
    Generate a unique ID from a URL.
    Uses the URL path as the ID (without domain).
    e.g. "https://anthropic.com/news/claude-3" → "anthropic_claude-3"
    """
    import hashlib
    # Use first 16 chars of URL hash as ID
    url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
    # Add source prefix from domain
    try:
        domain = url.split("/")[2].replace("www.", "").split(".")[0]
        return f"{domain}_{url_hash}"
    except Exception:
        return f"blog_{url_hash}"


def _parse_date(date_str: str) -> datetime:
    """Parse date strings from RSS/Atom feeds."""
    if not date_str:
        return datetime.now(timezone.utc)

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",       # RSS: Mon, 22 Mar 2025 00:00:00 GMT
        "%a, %d %b %Y %H:%M:%S GMT",       # RSS without timezone
        "%Y-%m-%dT%H:%M:%SZ",              # Atom UTC
        "%Y-%m-%dT%H:%M:%S%z",             # Atom with tz
        "%Y-%m-%dT%H:%M:%S.%fZ",           # Atom with microseconds
        "%Y-%m-%d",                         # Simple date
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return datetime.now(timezone.utc)


# ============================================================
# TEST
# Command: python scrapers/rss.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing RSS Blog Scraper")
    print(f"{'='*55}\n")

    print(f"Configured sources ({len(RSS_FEEDS)}):")
    for name, url in RSS_FEEDS.items():
        print(f"  {name:20} → {url}")

    print(f"\nFetching (max 3 per source)...")
    posts = await fetch_all_blogs(max_per_source=3)

    if posts:
        print(f"\n✅ Got {len(posts)} blog posts!\n")
        print("Sample posts:")
        for p in posts[:3]:
            print(f"\n  Source : {p.source}")
            print(f"  Title  : {p.title[:60]}")
            print(f"  Type   : {p.paper_type}")
            print(f"  Topic  : {p.topic}")
            print(f"  URL    : {p.url[:60]}")
            print(f"  Date   : {p.published_at.strftime('%Y-%m-%d')}")
    else:
        print("❌ No posts fetched — check internet connection")

    print(f"\n{'='*55}")
    print(f"  RSS scraper test done!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

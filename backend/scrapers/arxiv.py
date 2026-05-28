# ============================================================
# scrapers/arxiv.py — arXiv Paper Fetcher
# ============================================================
# Fetches the latest AI/ML papers from arXiv.
# arXiv is the world's largest open-access research repository.
# Their API is free, no key needed, and very reliable.
#
# Two modes:
#   1. fetch_latest()  → get newest papers (used by scheduler)
#   2. fetch_by_id()   → get one specific paper (used by Peeler)
#
# arXiv API docs: https://arxiv.org/help/api
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import httpx
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from config import ARXIV_CATEGORIES, MAX_PAPERS_PER_FETCH, DEBUG


# ============================================================
# PAPER DATACLASS
# ============================================================
# A clean Python object representing one research paper.
# Every scraper (arXiv, HuggingFace, blogs) returns Paper objects.
# This ensures processor.py always gets the same format
# regardless of which source the paper came from.

@dataclass
class Paper:
    # Core fields — always present
    id: str                          # unique ID e.g. "2301.00001"
    title: str                       # paper title
    abstract: str                    # abstract written by authors
    authors: list                    # list of author names
    url: str                         # link to paper page
    published_at: datetime           # when paper was published

    # Source info
    source: str = "arxiv"            # "arxiv", "huggingface", "blog"
    source_id: str = ""              # original ID from source

    # Classification — filled by processor.py
    topic: str = ""                  # "LLMs", "Computer Vision" etc.
    difficulty: str = "Intermediate" # "Easy", "Intermediate", "Advanced"
    paper_type: str = "paper"        # "paper", "model", "news"

    # Engagement — used for attention score (free user ranking)
    citation_count: int = 0
    hn_points: int = 0
    reddit_upvotes: int = 0

    # Processing flags
    summary: str = ""                # AI-generated summary (added by summarizer)
    has_peeler: bool = True          # can be peeled? (papers = yes, news = no)
    pdf_url: str = ""                # direct PDF link

    # Category tags
    categories: list = field(default_factory=list)  # e.g. ["cs.LG", "cs.AI"]


# ============================================================
# ARXIV API URLS
# ============================================================
# RSS feed → latest papers per category (last 24 hours)
ARXIV_RSS_URL = "http://export.arxiv.org/rss/{category}"

# Search API → search or fetch by ID
ARXIV_API_URL = "http://export.arxiv.org/api/query"

# XML namespaces used in arXiv responses
ARXIV_NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "arxiv":  "http://arxiv.org/schemas/atom",
    "dc":     "http://purl.org/dc/elements/1.1/",
    "media":  "http://search.yahoo.com/mrss/",
}


# ============================================================
# MAIN FUNCTION — fetch_latest()
# ============================================================

async def fetch_latest(
    categories: list = None,
    max_per_category: int = 20,
) -> list[Paper]:
    """
    Fetch the latest papers from arXiv across all configured categories.
    Called by scheduler every 5 minutes.

    Parameters:
        categories      → list of arXiv category codes
                          defaults to ARXIV_CATEGORIES from config.py
        max_per_category→ max papers to fetch per category

    Returns:
        List of Paper objects, deduplicated across categories
    """
    if categories is None:
        categories = ARXIV_CATEGORIES

    all_papers = []
    seen_ids = set()  # track IDs to avoid duplicates across categories

    print(f"\n📡 Fetching from arXiv ({len(categories)} categories)...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for category in categories:
            try:
                papers = await _fetch_category_rss(
                    client,
                    category,
                    max_per_category
                )

                # Deduplicate — a paper can appear in multiple categories
                new_papers = []
                for p in papers:
                    if p.id not in seen_ids:
                        seen_ids.add(p.id)
                        new_papers.append(p)

                all_papers.extend(new_papers)
                print(f"  ✅ {category:10} → {len(new_papers)} new papers")

                # Be respectful to arXiv — wait between requests
                # arXiv asks for 3 second delay between API calls
                await asyncio.sleep(3)

            except Exception as e:
                print(f"  ❌ {category:10} → Error: {str(e)[:60]}")
                continue

    print(f"\n  📦 Total fetched: {len(all_papers)} papers\n")
    return all_papers


# ============================================================
# FETCH ONE CATEGORY VIA RSS
# ============================================================

async def _fetch_category_rss(
    client: httpx.AsyncClient,
    category: str,
    max_results: int,
) -> list[Paper]:
    """
    Fetch latest papers from one arXiv category via RSS feed.
    RSS gives us papers from the last 24-48 hours.
    """
    url = ARXIV_RSS_URL.format(category=category)

    if DEBUG:
        print(f"  [arxiv] Fetching RSS: {url}")

    response = await client.get(url)
    response.raise_for_status()

    papers = _parse_rss(response.text, category)

    # Limit results
    return papers[:max_results]


# ============================================================
# PARSE RSS XML RESPONSE
# ============================================================

def _parse_rss(xml_text: str, category: str) -> list[Paper]:
    """
    Parse arXiv RSS XML and extract Paper objects.

    arXiv RSS format example:
    <item>
      <title>Paper Title (arXiv:2301.00001v1 [cs.LG])</title>
      <link>https://arxiv.org/abs/2301.00001</link>
      <description>Abstract text here...</description>
      <dc:creator>Author One, Author Two</dc:creator>
      <pubDate>Mon, 22 Mar 2025 00:00:00 GMT</pubDate>
    </item>
    """
    papers = []

    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return papers

        items = channel.findall("item")

        for item in items:
            try:
                paper = _parse_rss_item(item, category)
                if paper:
                    papers.append(paper)
            except Exception as e:
                if DEBUG:
                    print(f"  [arxiv] Failed to parse item: {e}")
                continue

    except ET.ParseError as e:
        print(f"  ❌ XML parse error: {e}")

    return papers


def _parse_rss_item(item, category: str) -> Optional[Paper]:
    """
    Parse a single RSS item into a Paper object.
    """
    # ── Title ──
    # arXiv title format: "Actual Title (arXiv:2301.00001v1 [cs.LG])"
    raw_title = item.findtext("title", "").strip()
    if not raw_title:
        return None

    # Remove the arXiv ID suffix from title
    # "Attention Is All You Need (arXiv:1706.03762v5 [cs.CL])"
    # → "Attention Is All You Need"
    title = raw_title
    if " (arXiv:" in title:
        title = title[:title.rfind(" (arXiv:")].strip()

    # ── URL and ID ──
    url = item.findtext("link", "").strip()
    if not url:
        return None

    # Extract arXiv ID from URL
    # "https://arxiv.org/abs/2301.00001" → "2301.00001"
    arxiv_id = url.rstrip("/").split("/")[-1]

    # Remove version suffix if present (e.g. "2301.00001v2" → "2301.00001")
    if "v" in arxiv_id:
        arxiv_id = arxiv_id.split("v")[0]

    # ── Abstract ──
    # In RSS, abstract is in <description> tag
    # Often has HTML tags — we clean those out
    abstract_raw = item.findtext("description", "").strip()
    abstract = _clean_html(abstract_raw)

    # Skip if abstract is too short (probably not a real paper)
    if len(abstract) < 50:
        return None

    # ── Authors ──
    # arXiv RSS uses Dublin Core: <dc:creator>
    dc_ns = "http://purl.org/dc/elements/1.1/"
    creator_el = item.find(f"{{{dc_ns}}}creator")
    if creator_el is not None and creator_el.text:
        # Authors are comma-separated: "Smith, John, Doe, Jane"
        authors_raw = creator_el.text.strip()
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
    else:
        authors = []

    # ── Published date ──
    pub_date_str = item.findtext("pubDate", "").strip()
    published_at = _parse_date(pub_date_str)

    # ── PDF URL ──
    pdf_url = url.replace("/abs/", "/pdf/") + ".pdf"

    # ── Build Paper object ──
    paper = Paper(
        id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=authors,
        url=url,
        published_at=published_at,
        source="arxiv",
        source_id=arxiv_id,
        paper_type="paper",
        has_peeler=True,        # all arXiv papers can be peeled
        pdf_url=pdf_url,
        categories=[category],
    )

    return paper


# ============================================================
# FETCH BY ID — for Paper Peeler
# ============================================================

async def fetch_by_id(arxiv_id: str) -> Optional[Paper]:
    """
    Fetch one specific paper by its arXiv ID.
    Used by Paper Peeler when user pastes an arXiv link.

    Accepts any of these formats:
        "2301.00001"
        "https://arxiv.org/abs/2301.00001"
        "https://arxiv.org/pdf/2301.00001.pdf"
        "arxiv:2301.00001"

    Returns:
        Paper object with full details
        None if paper not found
    """
    # Clean up the input — extract just the ID
    clean_id = _extract_arxiv_id(arxiv_id)
    if not clean_id:
        print(f"  ❌ Could not extract arXiv ID from: {arxiv_id}")
        return None

    if DEBUG:
        print(f"  [arxiv] Fetching paper by ID: {clean_id}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "id_list": clean_id,
                "max_results": 1,
            }
            response = await client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()

            papers = _parse_api_response(response.text)
            if papers:
                return papers[0]
            return None

    except Exception as e:
        print(f"  ❌ Error fetching paper {clean_id}: {e}")
        return None


def _parse_api_response(xml_text: str) -> list[Paper]:
    """
    Parse arXiv Atom API response (used for fetch_by_id).
    Different format from RSS — uses Atom namespace.
    """
    papers = []

    try:
        root = ET.fromstring(xml_text)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")

        for entry in entries:
            try:
                paper = _parse_atom_entry(entry)
                if paper:
                    papers.append(paper)
            except Exception as e:
                if DEBUG:
                    print(f"  [arxiv] Failed to parse entry: {e}")
                continue

    except ET.ParseError as e:
        print(f"  ❌ XML parse error: {e}")

    return papers


def _parse_atom_entry(entry) -> Optional[Paper]:
    """Parse a single Atom entry from arXiv API response."""
    ns = "http://www.w3.org/2005/Atom"
    arxiv_ns = "http://arxiv.org/schemas/atom"

    # Title
    title_el = entry.find(f"{{{ns}}}title")
    title = title_el.text.strip() if title_el is not None else ""
    if not title:
        return None

    # ID — arXiv ID URL like "http://arxiv.org/abs/2301.00001v1"
    id_el = entry.find(f"{{{ns}}}id")
    if id_el is None:
        return None
    arxiv_url = id_el.text.strip()
    arxiv_id = arxiv_url.split("/abs/")[-1]
    if "v" in arxiv_id:
        arxiv_id = arxiv_id.split("v")[0]

    # Abstract
    abstract_el = entry.find(f"{{{ns}}}summary")
    abstract = abstract_el.text.strip() if abstract_el is not None else ""
    abstract = _clean_html(abstract)

    # Authors
    author_els = entry.findall(f"{{{ns}}}author")
    authors = []
    for author_el in author_els:
        name_el = author_el.find(f"{{{ns}}}name")
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    # Published date
    published_el = entry.find(f"{{{ns}}}published")
    pub_str = published_el.text.strip() if published_el is not None else ""
    published_at = _parse_date(pub_str)

    # Links — find abs and pdf links
    url = f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # Categories
    category_els = entry.findall(f"{{{ns}}}category")
    categories = []
    for cat_el in category_els:
        term = cat_el.get("term", "")
        if term:
            categories.append(term)

    primary_category = categories[0] if categories else ""

    return Paper(
        id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=authors,
        url=url,
        published_at=published_at,
        source="arxiv",
        source_id=arxiv_id,
        paper_type="paper",
        has_peeler=True,
        pdf_url=pdf_url,
        categories=categories,
    )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _extract_arxiv_id(input_str: str) -> Optional[str]:
    """
    Extract clean arXiv ID from various input formats.

    Handles:
        "2301.00001"                              → "2301.00001"
        "2301.00001v2"                            → "2301.00001"
        "https://arxiv.org/abs/2301.00001"        → "2301.00001"
        "https://arxiv.org/pdf/2301.00001.pdf"    → "2301.00001"
        "arxiv:2301.00001"                        → "2301.00001"
        "arXiv:2301.00001"                        → "2301.00001"
    """
    import re

    s = input_str.strip()

    # Try to find the numeric ID pattern (YYMM.NNNNN)
    # arXiv IDs look like: 2301.00001 or 2301.000001
    match = re.search(r'(\d{4}\.\d{4,6})', s)
    if match:
        return match.group(1)

    # Old format: category/YYMMNNN e.g. cs/0601001
    match = re.search(r'([a-z\-]+/\d{7})', s)
    if match:
        return match.group(1)

    return None


def _clean_html(text: str) -> str:
    """
    Remove HTML tags from text.
    arXiv abstracts sometimes contain <p> and other tags.
    """
    import re
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Clean up whitespace
    clean = ' '.join(clean.split())
    return clean.strip()


def _parse_date(date_str: str) -> datetime:
    """
    Parse various date formats from arXiv responses.
    Returns UTC datetime, defaults to now if parsing fails.
    """
    if not date_str:
        return datetime.now(timezone.utc)

    # Try different date formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",     # RSS: "Mon, 22 Mar 2025 00:00:00 GMT"
        "%Y-%m-%dT%H:%M:%SZ",            # Atom: "2025-03-22T00:00:00Z"
        "%Y-%m-%dT%H:%M:%S%z",           # Atom with timezone
        "%Y-%m-%d",                       # Simple date
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # If all formats fail, return now
    return datetime.now(timezone.utc)


# ============================================================
# TEST — run this file directly
# Command: python scrapers/arxiv.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing arXiv Scraper")
    print(f"{'='*55}\n")

    # Test 1: Fetch latest papers (just 2 categories to be quick)
    print("Test 1: Fetching latest papers from cs.AI and cs.LG...")
    papers = await fetch_latest(
        categories=["cs.AI", "cs.LG"],
        max_per_category=5
    )

    if papers:
        print(f"\n  ✅ Got {len(papers)} papers!")
        print(f"\n  Sample paper:")
        p = papers[0]
        print(f"    ID        : {p.id}")
        print(f"    Title     : {p.title[:70]}...")
        print(f"    Authors   : {', '.join(p.authors[:3])}")
        print(f"    Published : {p.published_at.strftime('%Y-%m-%d')}")
        print(f"    URL       : {p.url}")
        print(f"    Abstract  : {p.abstract[:120]}...")
        print(f"    PDF URL   : {p.pdf_url}")
    else:
        print("  ❌ No papers fetched — check your internet connection")

    # Test 2: Fetch specific paper by ID
    print(f"\nTest 2: Fetching specific paper (Attention Is All You Need)...")
    paper = await fetch_by_id("1706.03762")

    if paper:
        print(f"  ✅ Got paper!")
        print(f"    Title   : {paper.title}")
        print(f"    Authors : {', '.join(paper.authors[:3])}")
        print(f"    URL     : {paper.url}")
    else:
        print("  ❌ Could not fetch specific paper")

    # Test 3: ID extraction
    print(f"\nTest 3: arXiv ID extraction...")
    test_inputs = [
        "2301.00001",
        "https://arxiv.org/abs/2301.00001",
        "https://arxiv.org/pdf/2301.00001.pdf",
        "arxiv:2301.00001",
        "arXiv:1706.03762v5",
    ]
    all_ok = True
    for inp in test_inputs:
        result = _extract_arxiv_id(inp)
        ok = "✅" if result else "❌"
        print(f"  {ok} '{inp}' → '{result}'")
        if not result:
            all_ok = False

    print(f"\n{'='*55}")
    if all_ok:
        print("  ✅ arXiv scraper working correctly!")
    else:
        print("  ⚠️  Some tests failed — check output above")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

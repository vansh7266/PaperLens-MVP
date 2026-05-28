# ============================================================
# scrapers/hackernews.py — Hacker News AI Posts Scraper
# ============================================================
# Fetches AI/ML related posts from Hacker News.
# HN = Hacker News (news.ycombinator.com)
# Official Firebase API — free, no key needed.
#
# Two purposes:
#   1. Discover AI news that isn't on arXiv or company blogs
#   2. Update attention scores for papers already in our DB
#      (if an arXiv paper gets 500 HN points → boost its score)
#
# API: https://hacker-news.firebaseio.com/v0/
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import httpx
import re
from datetime import datetime, timezone
from typing import Optional

from config import DEBUG
from scrapers.arxiv import Paper


# ============================================================
# SETTINGS
# ============================================================

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

# How many top stories to scan
TOP_STORIES_LIMIT = 200

# Minimum HN score (points) to include a story
MIN_HN_SCORE = 20

# AI/ML keywords to filter HN stories
AI_KEYWORDS = [
    "machine learning", "deep learning", "neural network",
    "artificial intelligence", " ai ", " llm ", " gpt ",
    "language model", "transformer", "diffusion", "openai",
    "anthropic", "google deepmind", "meta ai", "huggingface",
    "paper", "arxiv", "research", "model", "training",
    "fine-tuning", "reinforcement learning", "computer vision",
    "natural language", "chatgpt", "claude", "gemini", "llama",
    "mistral", "stable diffusion", "dall-e", "midjourney",
]


# ============================================================
# MAIN FUNCTION — fetch_hn_ai_posts()
# ============================================================

async def fetch_hn_ai_posts(
    max_stories: int = 20,
) -> tuple[list[Paper], list[dict]]:
    """
    Fetch AI/ML related posts from Hacker News.

    Returns TWO things:
        1. List of Paper objects (new stories not in our DB)
        2. List of score updates for existing papers
           [{"paper_id": "2301.00001", "hn_points": 450}]

    The score updates are used to boost attention scores
    of papers that are getting traction on HN.
    """
    print(f"\n🔶 Fetching Hacker News AI posts...")

    new_papers = []
    score_updates = []

    async with httpx.AsyncClient(timeout=20.0) as client:

        # Step 1: Get top story IDs
        story_ids = await _get_top_story_ids(client)
        if not story_ids:
            print("  ❌ Could not fetch HN stories")
            return [], []

        print(f"  Scanning top {len(story_ids)} stories...")

        # Step 2: Fetch story details in parallel (batches of 20)
        ai_stories = []
        for i in range(0, min(len(story_ids), TOP_STORIES_LIMIT), 20):
            batch_ids = story_ids[i:i + 20]
            batch_stories = await _fetch_stories_batch(client, batch_ids)

            # Filter to AI/ML stories only
            for story in batch_stories:
                if story and _is_ai_story(story):
                    ai_stories.append(story)

            # Small delay between batches
            await asyncio.sleep(0.3)

        print(f"  Found {len(ai_stories)} AI/ML stories")

        # Step 3: Process each AI story
        for story in ai_stories[:max_stories]:
            result = _process_story(story)
            if result:
                paper, score_update = result
                if paper:
                    new_papers.append(paper)
                if score_update:
                    score_updates.append(score_update)

    print(f"  📦 New HN papers: {len(new_papers)}")
    print(f"  📊 Score updates: {len(score_updates)}\n")

    return new_papers, score_updates


# ============================================================
# FETCH STORY IDS
# ============================================================

async def _get_top_story_ids(client: httpx.AsyncClient) -> list[int]:
    """Get the top story IDs from HN."""
    try:
        response = await client.get(f"{HN_API_BASE}/topstories.json")
        response.raise_for_status()
        ids = response.json()
        return ids[:TOP_STORIES_LIMIT]
    except Exception as e:
        if DEBUG:
            print(f"  [hn] Error fetching story IDs: {e}")
        return []


# ============================================================
# FETCH STORIES IN BATCH
# ============================================================

async def _fetch_stories_batch(
    client: httpx.AsyncClient,
    story_ids: list[int],
) -> list[Optional[dict]]:
    """
    Fetch multiple story details concurrently.
    """
    tasks = [_fetch_story(client, sid) for sid in story_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    stories = []
    for result in results:
        if isinstance(result, dict):
            stories.append(result)
    return stories


async def _fetch_story(
    client: httpx.AsyncClient,
    story_id: int,
) -> Optional[dict]:
    """Fetch one HN story by ID."""
    try:
        response = await client.get(
            f"{HN_API_BASE}/item/{story_id}.json"
        )
        response.raise_for_status()
        data = response.json()

        # Only return actual stories (not comments, jobs etc.)
        if data and data.get("type") == "story":
            return data
        return None

    except Exception:
        return None


# ============================================================
# FILTER AI STORIES
# ============================================================

def _is_ai_story(story: dict) -> bool:
    """
    Check if an HN story is about AI/ML.
    Checks title and URL against AI keywords.
    """
    if not story:
        return False

    # Must meet minimum score threshold
    score = story.get("score", 0)
    if score < MIN_HN_SCORE:
        return False

    # Check title and URL for AI keywords
    title = story.get("title", "").lower()
    url   = story.get("url", "").lower()
    text  = title + " " + url

    return any(kw in text for kw in AI_KEYWORDS)


# ============================================================
# PROCESS STORY
# ============================================================

def _process_story(story: dict) -> Optional[tuple]:
    """
    Process one AI story.

    Returns tuple of:
        (Paper object or None, score_update dict or None)

    If story links to an arXiv paper we might have:
        → return (None, {"paper_id": "...", "hn_points": 500})

    If story is new content:
        → return (Paper object, None)
    """
    if not story:
        return None

    title  = story.get("title", "").strip()
    url    = story.get("url", "")
    score  = story.get("score", 0)
    hn_id  = story.get("id", "")
    time   = story.get("time", 0)
    author = story.get("by", "")

    if not title or not url:
        return None

    # Check if this links to an arXiv paper
    arxiv_id = _extract_arxiv_id(url)
    if arxiv_id:
        # This is an arXiv paper with HN attention
        # Return a score update instead of a new Paper
        score_update = {
            "paper_id":  arxiv_id,
            "hn_points": score,
        }
        if DEBUG:
            print(f"  [hn] arXiv paper with {score} pts: {arxiv_id}")
        return None, score_update

    # New HN story (not an arXiv paper)
    # Convert to Paper object
    published_at = datetime.fromtimestamp(time, tz=timezone.utc) if time else datetime.now(timezone.utc)

    # Build unique ID
    item_id = f"hn_{hn_id}"

    # HN story URL as the "abstract"
    hn_url = f"https://news.ycombinator.com/item?id={hn_id}"
    description = f"Hacker News discussion with {score} points. Original: {url}"

    topic = _detect_hn_topic(title, url)

    paper = Paper(
        id=item_id,
        title=title,
        abstract=description,
        authors=[f"HN: {author}"] if author else ["Hacker News"],
        url=url or hn_url,
        published_at=published_at,
        source="hackernews",
        source_id=str(hn_id),
        paper_type="news",
        has_peeler=False,
        topic=topic,
        difficulty="Easy",
        hn_points=score,
    )

    return paper, None


# ============================================================
# HELPERS
# ============================================================

def _extract_arxiv_id(url: str) -> Optional[str]:
    """Extract arXiv paper ID from a URL if it's an arXiv link."""
    if not url or "arxiv.org" not in url:
        return None
    match = re.search(r'(\d{4}\.\d{4,6})', url)
    if match:
        return match.group(1)
    return None


def _detect_hn_topic(title: str, url: str) -> str:
    """Detect topic of an HN story."""
    text = (title + " " + url).lower()

    if any(w in text for w in ["language model", "llm", "gpt", "claude", "llama", "chatgpt"]):
        return "LLMs"
    if any(w in text for w in ["image", "vision", "diffusion", "dall-e", "midjourney", "stable"]):
        return "Computer Vision"
    if any(w in text for w in ["reinforcement", "agent", "reward", "robot"]):
        return "RL / Agents"
    if any(w in text for w in ["safety", "alignment", "bias", "hallucin"]):
        return "AI Safety"
    if any(w in text for w in ["multimodal", "vision-language"]):
        return "Multimodal"

    return "LLMs"


# ============================================================
# APPLY SCORE UPDATES TO DATABASE
# ============================================================

async def apply_hn_score_updates(score_updates: list[dict]) -> int:
    """
    Apply HN point updates to papers in the database.
    This boosts the attention score of papers getting HN traction.
    Called after fetch_hn_ai_posts().

    Returns:
        Number of papers updated
    """
    if not score_updates:
        return 0

    try:
        from core.database import get_service_client
        db = get_service_client()

        updated = 0
        for update in score_updates:
            try:
                db.table("papers").update({
                    "hn_points": update["hn_points"]
                }).eq("paper_id", update["paper_id"]).execute()
                updated += 1
            except Exception:
                continue

        if DEBUG:
            print(f"[hn] Updated {updated} papers with HN scores")
        return updated

    except Exception as e:
        print(f"❌ Error applying HN score updates: {e}")
        return 0


# ============================================================
# TEST
# Command: python scrapers/hackernews.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing Hacker News Scraper")
    print(f"{'='*55}\n")

    print("Fetching HN AI posts (max 10)...")
    papers, score_updates = await fetch_hn_ai_posts(max_stories=10)

    if papers:
        print(f"\n✅ Got {len(papers)} new HN stories!")
        for p in papers[:3]:
            print(f"\n  Title  : {p.title[:60]}")
            print(f"  URL    : {p.url[:60]}")
            print(f"  Points : {p.hn_points}")
            print(f"  Topic  : {p.topic}")
    else:
        print("  ℹ️  No new HN stories (all may be arXiv papers)")

    if score_updates:
        print(f"\n📊 arXiv papers with HN traction: {len(score_updates)}")
        for u in score_updates[:3]:
            print(f"  {u['paper_id']} → {u['hn_points']} HN points")

    print(f"\n{'='*55}")
    print(f"  Hacker News scraper test done!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

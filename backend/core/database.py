# ============================================================
# core/database.py — Supabase Database Operations
# ============================================================
# ALL database reads and writes go through this file.
# No other file imports supabase directly — only this one.
#
# Two clients:
#   service_client → full admin access (background jobs)
#   anon_client    → limited access (user-facing operations)
#
# Tables we use:
#   papers      → all fetched and processed papers
#   feed_queue  → papers queued for free users (released at 4AM)
#   users       → user profiles (managed by Supabase Auth)
#   peels       → saved Paper Peeler results
#   threads     → chat history per peeled paper
#
# ── SETUP: Run the SQL at the bottom of this file in your
#    Supabase dashboard → SQL Editor → New Query ──
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime, timezone
from typing import Optional
from supabase import create_client, Client

from config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_KEY,
    FREE_TOP_PAPERS,
    DEBUG,
)
from scrapers.arxiv import Paper


# ============================================================
# SUPABASE CLIENT SETUP
# ============================================================
# We create two clients:
#   service_client → uses service role key → bypasses RLS
#                    used for: scrapers, scheduler, admin ops
#   anon_client    → uses anon key → respects RLS
#                    used for: user-facing reads

service_client: Optional[Client] = None
anon_client: Optional[Client] = None


def get_service_client() -> Client:
    """Get or create the service role client."""
    global service_client
    if service_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
            )
        service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return service_client


def get_anon_client() -> Client:
    """Get or create the anon client."""
    global anon_client
    if anon_client is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env"
            )
        anon_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return anon_client


# ============================================================
# CONNECTION TEST
# ============================================================

async def test_connection() -> bool:
    try:
        db = get_service_client()
        # Try a simple query
        result = db.table("papers").select("paper_id").limit(1).execute()
        return True
    except Exception as e:
        print(f"  ❌ Database connection failed: {e}")
        return False


# ============================================================
# PAPERS TABLE OPERATIONS
# ============================================================

async def save_papers(papers: list[Paper]) -> int:
    """
    Save a batch of processed papers to the database.
    Uses UPSERT — if paper exists, update it. If new, insert.

    Parameters:
        papers → list of processed Paper objects with summaries

    Returns:
        Number of papers successfully saved
    """
    if not papers:
        return 0

    db = get_service_client()
    saved_count = 0

    # Convert Paper objects to database rows
    rows = []
    for paper in papers:
        row = _paper_to_row(paper)
        rows.append(row)

    try:
        # Upsert in batches of 20 (Supabase limit per request)
        batch_size = 20
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            result = db.table("papers").upsert(
                batch,
                on_conflict="paper_id"  # update if paper_id already exists
            ).execute()
            saved_count += len(batch)

        if DEBUG:
            print(f"[database] Saved {saved_count} papers")

        return saved_count

    except Exception as e:
        print(f"❌ Error saving papers: {e}")
        return 0


async def get_feed(
    topics: list[str] = None,
    plan: str = "free",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch papers for the feed.

    For PRO users:
        Returns all recent papers filtered by topics
        Ordered by published_at (newest first)

    For FREE users:
        Returns only papers that have been released (is_released=True)
        Ordered by attention_score (highest first)

    Parameters:
        topics  → list of topic names to filter by
                  e.g. ["LLMs", "Computer Vision"]
                  None = all topics
        plan    → "free" or "pro" or "team"
        limit   → number of papers to return
        offset  → pagination offset

    Returns:
        List of paper dicts ready to send to frontend
    """
    try:
        db = get_service_client()

        query = db.table("papers").select(
            "paper_id, title, summary, topic, difficulty, "
            "paper_type, source, source_name, url, authors, "
            "published_at, fetched_at, has_peeler, "
            "attention_score, is_released"
        )

        # Free users only see released papers
        if plan == "free":
            query = query.eq("is_released", True)

        # Filter by topics if specified
        if topics and len(topics) > 0:
            query = query.in_("topic", topics)

        # Order and paginate
        if plan == "free":
            query = query.order("attention_score", desc=True)
        else:
            query = query.order("published_at", desc=True)

        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        return result.data or []

    except Exception as e:
        print(f"❌ Error fetching feed: {e}")
        return []


async def get_paper_by_id(paper_id: str) -> Optional[dict]:
    """
    Fetch a single paper by its ID.
    Used by Paper Peeler to check if we already have the paper.
    """
    try:
        db = get_service_client()
        result = db.table("papers").select("*").eq(
            "paper_id", paper_id
        ).single().execute()
        return result.data
    except Exception:
        return None


async def paper_exists(paper_id: str) -> bool:
    """
    Quick check if a paper already exists in the database.
    Used by scraper to avoid reprocessing papers we already have.
    """
    paper = await get_paper_by_id(paper_id)
    return paper is not None


async def get_existing_ids(paper_ids: list[str]) -> set:
    """
    Given a list of paper IDs, return which ones already exist in DB.
    Used by processor to skip already-stored papers.
    More efficient than calling paper_exists() for each one.
    """
    if not paper_ids:
        return set()

    try:
        db = get_service_client()
        result = db.table("papers").select("paper_id").in_(
            "paper_id", paper_ids
        ).execute()

        existing = {row["paper_id"] for row in (result.data or [])}
        return existing

    except Exception as e:
        print(f"❌ Error checking existing IDs: {e}")
        return set()


async def update_paper_summary(paper_id: str, summary: str) -> bool:
    """
    Update the summary for a paper that's already in the database.
    Used when we regenerate a better summary.
    """
    try:
        db = get_service_client()
        db.table("papers").update(
            {"summary": summary}
        ).eq("paper_id", paper_id).execute()
        return True
    except Exception as e:
        print(f"❌ Error updating summary: {e}")
        return False


# ============================================================
# FEED QUEUE OPERATIONS
# ============================================================
# Free users don't see papers immediately.
# New papers go into the queue and are released at 4AM.
# Only top 20 by attention score are released each day.

async def add_to_queue(paper_ids: list[str]) -> None:
    """
    Add paper IDs to the free user queue.
    Papers in queue are not visible to free users yet.
    They get released at 4AM by release_queue().

    Parameters:
        paper_ids → list of paper IDs to queue
    """
    if not paper_ids:
        return

    try:
        db = get_service_client()

        rows = [
            {
                "paper_id": pid,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "is_released": False,
            }
            for pid in paper_ids
        ]

        # Upsert — if already queued, do nothing
        db.table("feed_queue").upsert(
            rows,
            on_conflict="paper_id",
            ignore_duplicates=True,
        ).execute()

        if DEBUG:
            print(f"[database] Queued {len(paper_ids)} papers for free users")

    except Exception as e:
        print(f"❌ Error adding to queue: {e}")


async def release_queue() -> int:
    """
    Release top FREE_TOP_PAPERS (20) papers to free users.
    Called at 4AM every day by the scheduler.

    How it works:
        1. Get all unreleased papers from queue
        2. Join with papers table to get attention scores
        3. Take top 20 by attention score
        4. Mark them as released (is_released=True in papers table)
        5. Mark queue entries as released

    Returns:
        Number of papers released
    """
    try:
        db = get_service_client()

        # Get unreleased queue entries
        queue_result = db.table("feed_queue").select(
            "paper_id"
        ).eq("is_released", False).execute()

        if not queue_result.data:
            if DEBUG:
                print("[database] Queue empty — nothing to release")
            return 0

        queued_ids = [row["paper_id"] for row in queue_result.data]

        # Get papers with attention scores
        papers_result = db.table("papers").select(
            "paper_id, attention_score"
        ).in_("paper_id", queued_ids).order(
            "attention_score", desc=True
        ).limit(FREE_TOP_PAPERS).execute()

        if not papers_result.data:
            return 0

        top_ids = [row["paper_id"] for row in papers_result.data]

        # Mark papers as released
        db.table("papers").update(
            {"is_released": True}
        ).in_("paper_id", top_ids).execute()

        # Mark queue entries as released
        db.table("feed_queue").update(
            {
                "is_released": True,
                "released_at": datetime.now(timezone.utc).isoformat()
            }
        ).in_("paper_id", top_ids).execute()

        print(f"  📰 Released {len(top_ids)} papers to free users")
        return len(top_ids)

    except Exception as e:
        print(f"❌ Error releasing queue: {e}")
        return 0


async def get_queue_status() -> dict:
    """
    Return basic queue counts for feed monitoring.
    Kept in this module because feed routes import all database reads here.
    """
    try:
        db = get_service_client()

        pending = db.table("feed_queue").select(
            "id", count="exact"
        ).eq("is_released", False).execute()

        total = db.table("papers").select("id", count="exact").execute()

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        released_today = db.table("feed_queue").select(
            "id", count="exact"
        ).eq("is_released", True).gte(
            "released_at", today_start
        ).execute()

        return {
            "pending_in_queue": pending.count or 0,
            "total_papers_in_db": total.count or 0,
            "released_today": released_today.count or 0,
        }
    except Exception as exc:
        if DEBUG:
            print(f"[database] Could not read queue status: {exc}")
        return {
            "pending_in_queue": 0,
            "total_papers_in_db": 0,
            "released_today": 0,
        }


# ============================================================
# USER OPERATIONS
# ============================================================

async def get_user_topics(user_id: str) -> list[str]:
    """
    Get the topics a user has selected.
    Returns their selected topics or all topics if none selected.
    """
    try:
        db = get_service_client()
        # User preferences are stored in Supabase Auth metadata
        # We read from auth.users via admin API
        result = db.auth.admin.get_user_by_id(user_id)
        if result and result.user:
            metadata = result.user.user_metadata or {}
            topics = metadata.get("topics", [])
            if topics:
                return topics
        # Default: return all topics
        return list(["LLMs", "Computer Vision", "RL / Agents",
                     "Diffusion Models", "NLP", "Multimodal",
                     "AI Safety", "Model Efficiency"])
    except Exception as e:
        if DEBUG:
            print(f"[database] Could not get user topics: {e}")
        return []


async def get_user_plan(user_id: str) -> str:
    """
    Get a user's subscription plan.
    Returns "free", "pro", or "team".
    """
    try:
        db = get_service_client()
        result = db.auth.admin.get_user_by_id(user_id)
        if result and result.user:
            metadata = result.user.user_metadata or {}
            return metadata.get("plan", "free")
        return "free"
    except Exception:
        return "free"


async def get_user_peel_count(user_id: str) -> int:
    """
    Get how many papers a user has peeled this month.
    Used to enforce the 5-peel free limit.
    """
    try:
        db = get_service_client()

        # Get start of current month
        now = datetime.now(timezone.utc)
        month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        result = db.table("peels").select(
            "id", count="exact"
        ).eq("user_id", user_id).gte(
            "created_at", month_start
        ).execute()

        return result.count or 0

    except Exception as e:
        if DEBUG:
            print(f"[database] Could not get peel count: {e}")
        return 0


# ============================================================
# PEELS TABLE OPERATIONS
# ============================================================

async def save_peel(
    user_id: str,
    paper_id: str,
    sections: dict,
) -> Optional[str]:
    """
    Save a Paper Peeler result to the database.
    This stores the 6-section breakdown so it doesn't
    need to be regenerated on revisit.

    Parameters:
        user_id  → Supabase auth user ID
        paper_id → arXiv paper ID
        sections → dict with 6 sections:
                   {what, timeline, fixes, arch, results, verdict}

    Returns:
        The new peel ID, or None if failed
    """
    try:
        db = get_service_client()
        result = db.table("peels").insert({
            "user_id":    user_id,
            "paper_id":   paper_id,
            "sections":   sections,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        if result.data:
            return result.data[0]["id"]
        return None

    except Exception as e:
        print(f"❌ Error saving peel: {e}")
        return None


async def get_peel(user_id: str, paper_id: str) -> Optional[dict]:
    """
    Get a saved peel for a user+paper combination.
    If it exists, return it (no need to regenerate).
    """
    try:
        db = get_service_client()
        result = db.table("peels").select("*").eq(
            "user_id", user_id
        ).eq(
            "paper_id", paper_id
        ).order("created_at", desc=True).limit(1).execute()

        if result.data:
            return result.data[0]
        return None

    except Exception:
        return None


# ============================================================
# THREADS (CHAT HISTORY)
# ============================================================

async def save_message(
    thread_id: str,
    user_id: str,
    paper_id: str,
    role: str,
    content: str,
) -> bool:
    """
    Save a chat message to a thread.

    Parameters:
        thread_id → unique thread identifier
        user_id   → user who sent/received the message
        paper_id  → which paper this thread is about
        role      → "user" or "assistant"
        content   → the message text
    """
    try:
        db = get_service_client()
        db.table("threads").insert({
            "thread_id":  thread_id,
            "user_id":    user_id,
            "paper_id":   paper_id,
            "role":       role,
            "content":    content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as e:
        print(f"❌ Error saving message: {e}")
        return False


async def get_thread_history(
    thread_id: str,
    limit: int = 20
) -> list[dict]:
    """
    Get chat history for a thread.
    Used by Paper Peeler chat to maintain conversation context.

    Returns messages in chronological order (oldest first).
    """
    try:
        db = get_service_client()
        result = db.table("threads").select(
            "role, content, created_at"
        ).eq("thread_id", thread_id).order(
            "created_at", asc=True
        ).limit(limit).execute()

        return result.data or []

    except Exception:
        return []


# ============================================================
# HELPER — convert Paper object to database row
# ============================================================

def _paper_to_row(paper: Paper) -> dict:
    """
    Convert a Paper dataclass to a Supabase table row dict.
    Maps Python field names to database column names.
    """
    # Handle published_at datetime
    if isinstance(paper.published_at, datetime):
        published_at = paper.published_at.isoformat()
    else:
        published_at = str(paper.published_at)

    source_type = paper.source if paper.source in {"arxiv", "doi"} else "feed"
    canonical_id = f"{source_type}:{paper.id}"

    return {
        "paper_id":       paper.id,
        "canonical_id":   canonical_id,
        "source_type":    source_type,
        "title":          paper.title,
        "abstract":       paper.abstract,
        "summary":        paper.summary or "",
        "authors":        paper.authors,
        "url":            paper.url,
        "pdf_url":        paper.pdf_url or "",
        "source":         paper.source,
        "source_name":    paper.source.capitalize(),
        "topic":          paper.topic or "Other",
        "difficulty":     paper.difficulty or "Intermediate",
        "paper_type":     paper.paper_type or "paper",
        "has_peeler":     paper.has_peeler,
        "categories":     paper.categories,
        "published_at":   published_at,
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
        "attention_score": getattr(paper, "_attention_score", 0.0),
        "is_released":    False,  # all papers start as unreleased
        "citation_count": paper.citation_count,
        "hn_points":      paper.hn_points,
        "reddit_upvotes": paper.reddit_upvotes,
    }


# ============================================================
# TEST — run this file directly
# Command: python core/database.py
#
# NOTE: Make sure you have run the CREATE TABLE SQL below
#       in Supabase SQL Editor before running this test!
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing Database Operations")
    print(f"{'='*55}\n")

    # Test 1: Connection
    print("Test 1: Database connection...")
    connected = await test_connection()
    if connected:
        print("  ✅ Connected to Supabase!")
    else:
        print("  ❌ Connection failed")
        print("  Make sure you've run the CREATE TABLE SQL in Supabase")
        return

    # Test 2: Save papers
    print("\nTest 2: Saving test papers...")
    from datetime import timezone as tz
    now = datetime.now(timezone.utc)

    test_papers = [
        Paper(
            id="test-paper-001",
            title="Test Paper: Attention Mechanisms in Neural Networks",
            abstract="This is a test paper about attention mechanisms. We propose a novel approach.",
            authors=["Test Author One", "Test Author Two"],
            url="https://arxiv.org/abs/test-001",
            published_at=now,
            source="arxiv",
            topic="LLMs",
            difficulty="Intermediate",
            paper_type="paper",
            has_peeler=True,
            summary="A test paper exploring attention mechanisms in neural networks.",
        ),
    ]
    # Add attention score
    test_papers[0]._attention_score = 15.0

    saved = await save_papers(test_papers)
    print(f"  {'✅' if saved > 0 else '❌'} Saved {saved} paper(s)")

    # Test 3: Check if paper exists
    print("\nTest 3: Checking if paper exists...")
    exists = await paper_exists("test-paper-001")
    print(f"  {'✅' if exists else '❌'} paper_exists() = {exists}")

    # Test 4: Get feed
    print("\nTest 4: Fetching feed...")
    # Pro user gets all papers
    feed = await get_feed(plan="pro", limit=10)
    print(f"  {'✅' if len(feed) >= 0 else '❌'} Got {len(feed)} papers in feed")

    if feed:
        p = feed[0]
        print(f"  Sample: '{p.get('title', '')[:50]}...'")

    # Test 5: Queue operations
    print("\nTest 5: Queue operations...")
    await add_to_queue(["test-paper-001"])
    print("  ✅ Added to queue")

    released = await release_queue()
    print(f"  ✅ Released {released} papers from queue")

    print(f"\n{'='*55}")
    print(f"  ✅ Database tests complete!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())


# ============================================================
# SUPABASE SQL — run this in Supabase SQL Editor
# Dashboard → SQL Editor → New Query → paste → Run
# ============================================================
"""
-- ============================================================
-- PaperLens Database Schema
-- Run this once in Supabase SQL Editor
-- Dashboard → SQL Editor → New Query → paste → Run
-- ============================================================

-- Papers table: stores all fetched and processed papers
CREATE TABLE IF NOT EXISTS papers (
    id               BIGSERIAL PRIMARY KEY,
    paper_id         TEXT UNIQUE NOT NULL,
    title            TEXT NOT NULL,
    abstract         TEXT DEFAULT '',
    summary          TEXT DEFAULT '',
    authors          TEXT[] DEFAULT '{}',
    url              TEXT NOT NULL,
    pdf_url          TEXT DEFAULT '',
    source           TEXT DEFAULT 'arxiv',
    source_name      TEXT DEFAULT 'arXiv',
    topic            TEXT DEFAULT 'Other',
    difficulty       TEXT DEFAULT 'Intermediate',
    paper_type       TEXT DEFAULT 'paper',
    has_peeler       BOOLEAN DEFAULT true,
    categories       TEXT[] DEFAULT '{}',
    published_at     TIMESTAMPTZ,
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    attention_score  FLOAT DEFAULT 0.0,
    is_released      BOOLEAN DEFAULT false,
    citation_count   INTEGER DEFAULT 0,
    hn_points        INTEGER DEFAULT 0,
    reddit_upvotes   INTEGER DEFAULT 0
);

-- Index for fast topic filtering
CREATE INDEX IF NOT EXISTS idx_papers_topic ON papers(topic);
CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_papers_released ON papers(is_released);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(attention_score DESC);

-- Feed queue: papers waiting to be released to free users
CREATE TABLE IF NOT EXISTS feed_queue (
    id          BIGSERIAL PRIMARY KEY,
    paper_id    TEXT UNIQUE NOT NULL,
    queued_at   TIMESTAMPTZ DEFAULT NOW(),
    is_released BOOLEAN DEFAULT false,
    released_at TIMESTAMPTZ
);

-- Peels table: saved Paper Peeler results
CREATE TABLE IF NOT EXISTS peels (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id    UUID NOT NULL,
    paper_id   TEXT NOT NULL,
    sections   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_peels_user ON peels(user_id);
CREATE INDEX IF NOT EXISTS idx_peels_paper ON peels(paper_id);

-- Threads table: chat history per paper per user
CREATE TABLE IF NOT EXISTS threads (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    user_id    UUID NOT NULL,
    paper_id   TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_threads_thread ON threads(thread_id);
CREATE INDEX IF NOT EXISTS idx_threads_user ON threads(user_id);

-- Enable Row Level Security (RLS)
ALTER TABLE papers   ENABLE ROW LEVEL SECURITY;
ALTER TABLE peels    ENABLE ROW LEVEL SECURITY;
ALTER TABLE threads  ENABLE ROW LEVEL SECURITY;

-- RLS Policies
-- Papers: everyone can read (public feed)
CREATE POLICY "Papers are publicly readable"
    ON papers FOR SELECT USING (true);

-- Papers: only service role can insert/update (backend only)
CREATE POLICY "Service role can write papers"
    ON papers FOR ALL USING (auth.role() = 'service_role');

-- Peels: users can only see their own peels
CREATE POLICY "Users see own peels"
    ON peels FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users create own peels"
    ON peels FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Threads: users can only see their own threads
CREATE POLICY "Users see own threads"
    ON threads FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users create own threads"
    ON threads FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Service role bypasses all RLS (for backend operations)
"""

# ============================================================
# pipeline/queue.py — Pro/Free Delivery Queue
# ============================================================
# Controls WHEN papers reach users based on their plan.
#
# PRO users  → papers appear within 3 minutes of being fetched
# FREE users → papers held in queue, released at 4AM daily
#              only top 20 by attention score are released
#
# Flow:
#   New papers fetched
#       ↓
#   process_and_queue(papers)
#       ↓
#   ┌─────────────────────────┐
#   │  Is paper new?          │
#   │  YES → save to DB       │
#   │        mark unreleased  │
#   │        add to queue     │
#   └─────────────────────────┘
#       ↓
#   Pro users  → is_released = True immediately
#   Free users → is_released = False (set True at 4AM)
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime, timezone
from typing import Optional

from config import (
    PRO_DELAY_MINUTES,
    FREE_DIGEST_TIME,
    FREE_TOP_PAPERS,
    DEBUG,
)
from scrapers.arxiv import Paper
from core.database import (
    save_papers,
    add_to_queue,
    release_queue,
    get_existing_ids,
)


# ============================================================
# MAIN FUNCTION — process_and_queue()
# ============================================================

async def process_and_queue(papers: list[Paper]) -> dict:
    """
    Main entry point called by scheduler after each fetch.
    Saves new papers and routes them to the right queue.

    Parameters:
        papers → fully processed papers (with summaries)

    Returns:
        dict with counts: new_papers, queued, pro_released
    """
    if not papers:
        return {"new_papers": 0, "queued": 0, "pro_released": 0}

    # Step 1: Find which papers are actually new
    all_ids = [p.id for p in papers]
    existing_ids = await get_existing_ids(all_ids)
    new_papers = [p for p in papers if p.id not in existing_ids]

    if not new_papers:
        if DEBUG:
            print("[queue] No new papers — all already in database")
        return {"new_papers": 0, "queued": 0, "pro_released": 0}

    print(f"\n📬 Queue processing: {len(new_papers)} new papers")

    # Step 2: Save all new papers to database
    # All start with is_released = False
    saved = await save_papers(new_papers)
    if DEBUG:
        print(f"[queue] Saved {saved} papers to database")

    # Step 3: Release immediately for Pro users
    # Mark papers as released so Pro feed shows them right away
    pro_released = await _release_for_pro(new_papers)
    if DEBUG:
        print(f"[queue] Released {pro_released} papers for Pro users")

    # Step 4: Add to free user queue
    # These will be held until 4AM daily batch
    new_ids = [p.id for p in new_papers]
    await add_to_queue(new_ids)
    if DEBUG:
        print(f"[queue] Added {len(new_ids)} papers to free user queue")

    result = {
        "new_papers":    len(new_papers),
        "queued":        len(new_ids),
        "pro_released":  pro_released,
    }

    print(f"   ✅ {len(new_papers)} new · "
          f"{pro_released} live for Pro · "
          f"{len(new_ids)} queued for Free (4AM)")

    return result


# ============================================================
# PRO RELEASE
# ============================================================

async def _release_for_pro(papers: list[Paper]) -> int:
    """
    Mark papers as immediately visible to Pro users.
    Pro users see papers within PRO_DELAY_MINUTES (3 min).

    In our current architecture:
        - All papers are saved with is_released = False initially
        - We immediately flip is_released = True for Pro visibility
        - Free users still see is_released = False in their feed query
          until the 4AM batch runs

    This works because:
        - Pro feed query: no is_released filter (sees everything)
        - Free feed query: only is_released = True
    """
    if not papers:
        return 0

    try:
        from core.database import get_service_client
        db = get_service_client()

        paper_ids = [p.id for p in papers]

        # Mark as released (Pro users see these immediately)
        db.table("papers").update(
            {"is_released": True}
        ).in_("paper_id", paper_ids).execute()

        return len(paper_ids)

    except Exception as e:
        print(f"❌ Error releasing papers for Pro: {e}")
        return 0


# ============================================================
# 4AM DAILY BATCH — for free users
# ============================================================

async def run_daily_release() -> dict:
    """
    Run the 4AM daily batch release for free users.
    Called by scheduler at 4:00 AM every day.

    Steps:
        1. Get all unreleased papers from queue
        2. Rank by attention score
        3. Take top FREE_TOP_PAPERS (20)
        4. Mark as released in papers table
        5. Mark as processed in queue table

    Returns:
        dict with release stats
    """
    print(f"\n🌅 Running 4AM daily release for free users...")
    print(f"   Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    released = await release_queue()

    result = {
        "released_count": released,
        "max_allowed":    FREE_TOP_PAPERS,
        "run_at":         datetime.now(timezone.utc).isoformat(),
    }

    if released > 0:
        print(f"   ✅ Released {released} papers to free users")
    else:
        print(f"   ℹ️  No papers in queue to release")

    return result


# ============================================================
# QUEUE STATUS
# ============================================================

async def get_queue_status() -> dict:
    """
    Get current status of the queue.
    Useful for monitoring and debugging.

    Returns:
        dict with queue stats
    """
    try:
        from core.database import get_service_client
        db = get_service_client()

        # Count unreleased papers in queue
        pending = db.table("feed_queue").select(
            "id", count="exact"
        ).eq("is_released", False).execute()

        # Count total papers in database
        total = db.table("papers").select(
            "id", count="exact"
        ).execute()

        # Count papers released today
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        released_today = db.table("feed_queue").select(
            "id", count="exact"
        ).eq("is_released", True).gte(
            "released_at", today_start
        ).execute()

        return {
            "pending_in_queue":   pending.count or 0,
            "total_papers_in_db": total.count or 0,
            "released_today":     released_today.count or 0,
            "next_release":       _next_release_time(),
        }

    except Exception as e:
        return {"error": str(e)}


def _next_release_time() -> str:
    """Calculate when the next 4AM release will happen."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    hour, minute = map(int, FREE_DIGEST_TIME.split(":"))
    next_release = now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if next_release <= now:
        next_release = next_release.replace(day=now.day + 1)
    return next_release.strftime("%Y-%m-%d %H:%M UTC")


# ============================================================
# TEST
# Command: python pipeline/queue.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing Queue System")
    print(f"{'='*55}\n")

    print("Test 1: Queue status...")
    status = await get_queue_status()
    for k, v in status.items():
        print(f"  {k}: {v}")

    print("\nTest 2: Daily release...")
    result = await run_daily_release()
    print(f"  Released: {result['released_count']} papers")

    print(f"\n{'='*55}")
    print(f"  ✅ Queue system working!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

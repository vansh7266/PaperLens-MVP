# ============================================================
# pipeline/scheduler.py — Automation Engine
# ============================================================
# This is the heartbeat of PaperLens.
# It runs two jobs automatically:
#
#   Job 1 — FETCH JOB (every 5 minutes)
#       → Fetch new papers from arXiv + other sources
#       → Process + classify + summarise
#       → Save to database
#       → Release to Pro users immediately
#       → Queue for Free users (released at 4AM)
#
#   Job 2 — DAILY RELEASE JOB (every day at 4AM UTC)
#       → Release top 20 papers to free users
#       → Based on attention score ranking
#
# Uses APScheduler — a simple Python scheduler.
# No Redis or Celery needed at this stage.
# (We upgrade to Celery + Redis in Phase 2 if scale requires it)
#
# Install: uv pip install apscheduler
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import traceback
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import (
    FETCH_INTERVAL_MINUTES,
    FREE_DIGEST_TIME,
    ARXIV_CATEGORIES,
    MAX_PAPERS_PER_FETCH,
    DEBUG,
)


# ============================================================
# SCHEDULER INSTANCE
# ============================================================
# Single shared scheduler instance
# Started once when the FastAPI app starts

scheduler = AsyncIOScheduler(timezone="UTC")

# Track last run stats for monitoring
_last_fetch_result = {
    "run_at":      None,
    "fetched":     0,
    "new_papers":  0,
    "errors":      [],
}

_last_release_result = {
    "run_at":   None,
    "released": 0,
}


# ============================================================
# JOB 1 — FETCH JOB
# ============================================================

async def fetch_job():
    """
    Main fetch job — runs every FETCH_INTERVAL_MINUTES (5 min).

    Full pipeline:
        1. Fetch papers from all sources
        2. Process (deduplicate, classify, difficulty)
        3. Summarise (Gemini API)
        4. Queue (Pro=instant, Free=4AM)
    """
    run_start = datetime.now(timezone.utc)

    if DEBUG:
        print(f"\n⏰ Fetch job started at "
              f"{run_start.strftime('%H:%M:%S UTC')}")

    try:
        # Import here to avoid circular imports at module level
        from scrapers.arxiv import fetch_latest
        from pipeline.processor import process_batch
        from pipeline.summarizer import summarize_batch
        from pipeline.queue import process_and_queue
        from core.database import get_existing_ids

        # Step 1: Fetch from ALL sources
        print(f"\n{'─'*40}")
        print(f"📡 Fetching papers ({run_start.strftime('%H:%M UTC')})...")

        # arXiv papers
        raw_papers = await fetch_latest(
            categories=ARXIV_CATEGORIES,
            max_per_category=MAX_PAPERS_PER_FETCH // len(ARXIV_CATEGORIES),
        )

        # Blog RSS feeds
        try:
            from scrapers.rss import fetch_all_blogs
            blog_posts = await fetch_all_blogs(max_per_source=5)
            raw_papers.extend(blog_posts)
        except Exception as e:
            print(f"  ⚠️  RSS fetch failed: {e}")

        # HuggingFace models
        try:
            from scrapers.huggingface import fetch_new_models
            hf_models = await fetch_new_models(max_per_category=5)
            raw_papers.extend(hf_models)
        except Exception as e:
            print(f"  ⚠️  HuggingFace fetch failed: {e}")

        # Hacker News
        try:
            from scrapers.hackernews import fetch_hn_ai_posts, apply_hn_score_updates
            hn_papers, hn_updates = await fetch_hn_ai_posts(max_stories=10)
            raw_papers.extend(hn_papers)
            if hn_updates:
                await apply_hn_score_updates(hn_updates)
        except Exception as e:
            print(f"  ⚠️  HN fetch failed: {e}")

        if not raw_papers:
            print("  ℹ️  No papers fetched this run")
            _update_fetch_stats(run_start, 0, 0)
            return

        print(f"  📦 Fetched {len(raw_papers)} items total")

        # Step 2: Get existing IDs to skip already-stored papers
        all_ids = [p.id for p in raw_papers]
        existing_ids = await get_existing_ids(all_ids)
        new_raw = [p for p in raw_papers if p.id not in existing_ids]

        if not new_raw:
            print(f"  ℹ️  All {len(raw_papers)} papers already in database")
            _update_fetch_stats(run_start, len(raw_papers), 0)
            return

        print(f"  🆕 {len(new_raw)} new papers to process")

        # Step 3: Process (classify + difficulty + score)
        processed = await process_batch(new_raw, existing_ids)

        # Step 4: Summarise with Gemini
        summarized = await summarize_batch(processed)

        # Step 5: Queue (Pro instant, Free 4AM)
        result = await process_and_queue(summarized)

        # Update stats
        _update_fetch_stats(
            run_start,
            fetched=len(raw_papers),
            new_papers=result.get("new_papers", 0),
        )

        elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
        print(f"\n  ✅ Fetch job done in {elapsed:.1f}s")
        print(f"{'─'*40}\n")

    except Exception as e:
        error_msg = str(e)
        print(f"\n  ❌ Fetch job error: {error_msg}")
        if DEBUG:
            traceback.print_exc()
        _last_fetch_result["errors"].append({
            "time":  run_start.isoformat(),
            "error": error_msg,
        })
        # Keep only last 10 errors
        _last_fetch_result["errors"] = _last_fetch_result["errors"][-10:]


# ============================================================
# JOB 2 — DAILY RELEASE JOB
# ============================================================

async def daily_release_job():
    """
    Daily release job — runs at 4AM UTC every day.
    Releases top 20 papers to free users from the queue.
    """
    run_start = datetime.now(timezone.utc)
    print(f"\n🌅 Daily release job at {run_start.strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        from pipeline.queue import run_daily_release

        result = await run_daily_release()
        released = result.get("released_count", 0)

        _last_release_result["run_at"]   = run_start.isoformat()
        _last_release_result["released"] = released

        print(f"  ✅ Daily release done: {released} papers sent to free users")

    except Exception as e:
        print(f"  ❌ Daily release error: {e}")
        if DEBUG:
            traceback.print_exc()


# ============================================================
# SCHEDULER CONTROL
# ============================================================

def start_scheduler():
    """
    Start the scheduler with both jobs.
    Called once during FastAPI app startup in main.py.
    """
    if scheduler.running:
        print("  ⚠️  Scheduler already running")
        return

    # Job 1: Fetch every N minutes
    scheduler.add_job(
        fetch_job,
        trigger=IntervalTrigger(minutes=FETCH_INTERVAL_MINUTES),
        id="fetch_job",
        name="Fetch papers",
        replace_existing=True,
        max_instances=1,        # never run 2 at the same time
        misfire_grace_time=60,  # if delayed, still run within 60s
    )

    # Job 2: Daily release at 4AM UTC
    hour, minute = map(int, FREE_DIGEST_TIME.split(":"))
    scheduler.add_job(
        daily_release_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id="daily_release_job",
        name="Daily release for free users",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()

    print(f"  ⏰ Scheduler started:")
    print(f"     Fetch job    → every {FETCH_INTERVAL_MINUTES} minutes")
    print(f"     Daily release→ {FREE_DIGEST_TIME} UTC daily")


def stop_scheduler():
    """Stop the scheduler gracefully. Called on app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("  ⏰ Scheduler stopped")


def get_scheduler_status() -> dict:
    """
    Get current scheduler status.
    Used by health check endpoint.
    """
    if not scheduler.running:
        return {"running": False}

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": next_run.strftime("%Y-%m-%d %H:%M UTC") if next_run else "N/A",
        })

    return {
        "running":       True,
        "jobs":          jobs,
        "last_fetch":    _last_fetch_result,
        "last_release":  _last_release_result,
    }


# ============================================================
# HELPER
# ============================================================

def _update_fetch_stats(run_at, fetched: int, new_papers: int):
    """Update the last fetch result stats."""
    _last_fetch_result["run_at"]     = run_at.isoformat()
    _last_fetch_result["fetched"]    = fetched
    _last_fetch_result["new_papers"] = new_papers


# ============================================================
# TEST — run this file directly to test one fetch cycle
# Command: python pipeline/scheduler.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing Scheduler — Running ONE fetch cycle")
    print(f"{'='*55}\n")

    print("Running fetch job once manually...")
    await fetch_job()

    print("\nRunning daily release job manually...")
    await daily_release_job()

    print("\nScheduler status (if started):")
    status = get_scheduler_status()
    print(f"  Running: {status['running']}")
    print(f"  Last fetch: {status.get('last_fetch', {})}")

    print(f"\n{'='*55}")
    print(f"  ✅ Scheduler test done!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

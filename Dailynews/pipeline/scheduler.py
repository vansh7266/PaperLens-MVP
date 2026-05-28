# pipeline/scheduler.py

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from core.database import get_service_client
from scrapers.arxiv import ArxivScraper
from scrapers.huggingface import HuggingFaceScraper
from scrapers.rss_blogs import RSSBlogScraper
from pipeline.processor import Processor
from pipeline.summarizer import Summarizer

logger = logging.getLogger("paperlens.pipeline.scheduler")


class PipelineScheduler:
    """
    Orchestrates the full PaperLens content pipeline.

    Manages two APScheduler jobs:
      1. pipeline_cycle() — runs every 30 minutes
         Scrape → Process → Insert → Summarize
      2. free_tier_batch() — runs once daily at 4AM UTC
         Releases top 20 unreleased items to free tier users

    Owns all scraper instances — creates them once, reuses connection pools.
    Shuts down scrapers gracefully when the app stops.
    """

    def __init__(self):
        """
        Initialize scrapers, processor, summarizer, and APScheduler.

        All scrapers created here so their httpx.AsyncClient instances
        (connection pools) are reused across every 30-min cycle.
        """
        # --- Scrapers: one instance each, connection pool reused per cycle ---
        self.arxiv_scraper = ArxivScraper()
        self.hf_scraper = HuggingFaceScraper()
        self.blog_scraper = RSSBlogScraper()

        # --- Pipeline stages ---
        self.processor = Processor()
        self.summarizer = Summarizer()

        # --- APScheduler: AsyncIOScheduler runs jobs on the existing event loop ---
        self.scheduler = AsyncIOScheduler(timezone="UTC")

        logger.info("[Scheduler] Initialized. Scrapers and pipeline stages ready.")

    # -----------------------------------------------------------------------
    # Scheduler start/stop
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """
        Register jobs and start the scheduler.

        Called once in main.py on app startup.
        """
        # Job 1: Full pipeline — every 30 minutes
        self.scheduler.add_job(
            self.pipeline_cycle,
            trigger=IntervalTrigger(minutes=config.SCHEDULER_INTERVAL_MINUTES),
            id="pipeline_cycle",
            name="30-min content pipeline",
            next_run_time=datetime.now(timezone.utc),
            max_instances=1,
            coalesce=True,
        )

        # Job 2: Free tier batch — every day at 4AM UTC
        self.scheduler.add_job(
            self.free_tier_batch,
            trigger=CronTrigger(hour=config.FREE_TIER_RELEASE_HOUR_UTC, minute=0),
            id="free_tier_batch",
            name="4AM free tier release",
            max_instances=1,
        )

        self.scheduler.start()
        logger.info(
            f"[Scheduler] Started. "
            f"Pipeline: every {config.SCHEDULER_INTERVAL_MINUTES} min | "
            f"Free batch: daily at {config.FREE_TIER_RELEASE_HOUR_UTC}:00 UTC"
        )

    async def stop(self) -> None:
        """
        Gracefully shut down scheduler and close all scraper HTTP clients.

        Called in main.py on app shutdown.
        """
        self.scheduler.shutdown(wait=True)
        logger.info("[Scheduler] APScheduler stopped.")

        await asyncio.gather(
            self.arxiv_scraper.close(),
            self.hf_scraper.close(),
            self.blog_scraper.close(),
        )
        logger.info("[Scheduler] All scraper clients closed.")

    # -----------------------------------------------------------------------
    # DB helpers
    # -----------------------------------------------------------------------

    async def _insert_items(self, items: list[dict]) -> list[dict]:
        """
        Insert processed items into content_items table.

        Assigns UUIDs in Python before insert so summarizer has IDs
        without relying on DB returning rows (avoids PostgREST compat issues).

        Uses upsert with on_conflict="source_url" — silently skips duplicates.

        Args:
            items: Processed item dicts from processor.process_items()

        Returns:
            Same items with 'id' field populated.
            Returns [] on failure — pipeline continues without crashing.
        """
        if not items:
            return []

        try:
            # Assign UUIDs in Python — avoids needing DB to return them
            for item in items:
                item["id"] = str(uuid.uuid4())

            db = await get_service_client()

            # Simple upsert — supabase-py v2 compatible
            response = await (
                db.table("content_items")
                .upsert(items, on_conflict="source_url")
                .execute()
            )

            logger.info(f"[Scheduler] Inserted {len(items)} items into DB.")
            return items

        except Exception as e:
            logger.error(
                f"[Scheduler] DB insert failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

    # -----------------------------------------------------------------------
    # Job 1: 30-minute pipeline cycle
    # -----------------------------------------------------------------------

    async def pipeline_cycle(self) -> None:
        """
        Full pipeline cycle — runs every 30 minutes.

        Steps:
          1. Scrape all 3 sources in parallel
          2. Flatten + deduplicate by source_url (in-memory)
          3. Process items (topic, difficulty, attention score, DB dedup check)
          4. Insert new items into DB (assign UUIDs in Python)
          5. Summarize inserted items (LLM generates 2-3 line summaries)

        One scraper failing does not stop the others or crash the cycle.
        """
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"[Scheduler] Pipeline cycle starting at {cycle_start.isoformat()}")

        try:
            # --- Step 1: Scrape all sources in parallel ---
            scrape_results = await asyncio.gather(
                self.arxiv_scraper.scrape(),
                self.hf_scraper.scrape(),
                self.blog_scraper.scrape(),
                return_exceptions=True,
            )

            raw_items = []
            scraper_names = ["arXiv", "HuggingFace", "RSSBlogs"]
            for name, result in zip(scraper_names, scrape_results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[Scheduler] {name} scraper raised exception: "
                        f"{type(result).__name__}: {result}"
                    )
                else:
                    logger.info(f"[Scheduler] {name}: {len(result)} items scraped.")
                    raw_items.extend(result)

            if not raw_items:
                logger.warning("[Scheduler] No items from any scraper this cycle.")
                return

            # --- Step 2: In-memory dedup by source_url ---
            seen_urls = set()
            deduplicated = []
            for item in raw_items:
                url = item.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduplicated.append(item)

            logger.info(
                f"[Scheduler] {len(raw_items)} raw → {len(deduplicated)} after in-memory dedup."
            )

            # --- Step 3: Process items ---
            processed_items = await self.processor.process_items(deduplicated)

            if not processed_items:
                logger.info("[Scheduler] No new items after processing. Cycle complete.")
                return

            logger.info(f"[Scheduler] {len(processed_items)} new items after processing.")

            # --- Step 4: Insert into DB — items now have 'id' field ---
            inserted_items = await self._insert_items(processed_items)

            if not inserted_items:
                logger.warning("[Scheduler] No items inserted into DB. Skipping summarization.")
                return

            # --- Step 5: Summarize inserted items ---
            summarized_items = await self.summarizer.summarize_batch(inserted_items)

            success_count = sum(1 for item in summarized_items if item.get("is_summarized"))

            # --- Cycle summary log ---
            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(
                f"[Scheduler] Cycle complete in {elapsed:.1f}s. "
                f"Scraped: {len(raw_items)} | "
                f"New: {len(processed_items)} | "
                f"Inserted: {len(inserted_items)} | "
                f"Summarized: {success_count}"
            )

        except Exception as e:
            logger.error(
                f"[Scheduler] Unhandled exception in pipeline_cycle: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # Job 2: 4AM UTC free tier batch
    # -----------------------------------------------------------------------

    async def free_tier_batch(self) -> None:
        """
        Daily 4AM UTC job — releases top 20 items to free tier users.

        Selects top 20 unreleased + summarized items from last 24 hours
        and marks them is_released=True.
        """
        logger.info("[Scheduler] 4AM free tier batch starting.")

        try:
            db = await get_service_client()

            # Only consider items from last 24 hours — prevents stale items
            yesterday_iso = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()

            response = await (
                db.table("content_items")
                .select("id")
                .eq("is_released", False)
                .eq("is_summarized", True)
                .gte("fetched_at", yesterday_iso)
                .order("attention_score", desc=True)
                .limit(config.FREE_TIER_DAILY_LIMIT)
                .execute()
            )

            items = response.data or []

            if not items:
                logger.info("[Scheduler] No unreleased items found for free tier batch.")
                return

            ids_to_release = [item["id"] for item in items]

            await (
                db.table("content_items")
                .update({
                    "is_released": True,
                    "released_at": datetime.now(timezone.utc).isoformat(),
                })
                .in_("id", ids_to_release)
                .execute()
            )

            logger.info(
                f"[Scheduler] Free tier batch complete. "
                f"Released {len(ids_to_release)} items."
            )

        except Exception as e:
            logger.error(
                f"[Scheduler] Free tier batch failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
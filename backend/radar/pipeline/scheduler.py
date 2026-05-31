# radar/pipeline/scheduler.py
#
# Orchestrates the full Research Radar content pipeline.
# Two APScheduler jobs:
#   1. pipeline_cycle() — every 30 min
#      Scrape → Process → Insert → Summarize
#   2. free_tier_batch() — daily at 4AM UTC
#      Release top items to free tier users

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from radar.scrapers.arxiv import ArxivScraper
from radar.scrapers.huggingface import HuggingFaceScraper
from radar.scrapers.rss_blogs import RSSBlogScraper
from radar.pipeline.processor import Processor
from radar.pipeline.summarizer import Summarizer
from radar.core.database import get_service_client
from radar.pipeline.digest import DigestSender
from config import (
    RADAR_SCHEDULER_INTERVAL_MINUTES,
    RADAR_FREE_RELEASE_HOUR_UTC,
    RADAR_FREE_DAILY_LIMIT,
    RADAR_DIGEST_HOUR_UTC,
)

logger = logging.getLogger("paperlens.radar.pipeline.scheduler")


class RadarScheduler:
    """
    Orchestrates the Radar content pipeline.

    Owns all scraper instances — created once, connection pools reused.
    Started by main.py lifespan. Stopped gracefully on shutdown.
    """

    def __init__(self):
        # One scraper instance each — connection pools are reused per cycle
        self.arxiv_scraper = ArxivScraper()
        self.hf_scraper    = HuggingFaceScraper()
        self.blog_scraper  = RSSBlogScraper()

        self.processor      = Processor()
        self.summarizer     = Summarizer()
        self.digest_sender  = DigestSender()

        # AsyncIOScheduler runs jobs on the existing FastAPI event loop
        self.scheduler = AsyncIOScheduler(timezone="UTC")

        logger.info("[RadarScheduler] Initialized.")

    # -----------------------------------------------------------------------
    # Start / stop
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Register both jobs and start the scheduler. Called once on startup."""
        # Job 1: Full pipeline every N minutes
        self.scheduler.add_job(
            self.pipeline_cycle,
            trigger=IntervalTrigger(minutes=RADAR_SCHEDULER_INTERVAL_MINUTES),
            id="radar_pipeline_cycle",
            name=f"Radar pipeline — every {RADAR_SCHEDULER_INTERVAL_MINUTES} min",
            next_run_time=datetime.now(timezone.utc),  # run immediately at startup
            max_instances=1,
            coalesce=True,
        )

        # Job 2: Free tier batch — once daily at 4AM UTC
        self.scheduler.add_job(
            self.free_tier_batch,
            trigger=CronTrigger(hour=RADAR_FREE_RELEASE_HOUR_UTC, minute=0),
            id="radar_free_tier_batch",
            name="Radar 4AM free tier release",
            max_instances=1,
        )

        # Job 3: Daily email digest — once daily at RADAR_DIGEST_HOUR_UTC (default 8AM UTC)
        self.scheduler.add_job(
            self.daily_digest_job,
            trigger=CronTrigger(hour=RADAR_DIGEST_HOUR_UTC, minute=0),
            id="radar_daily_digest",
            name=f"Radar daily digest — {RADAR_DIGEST_HOUR_UTC}:00 UTC",
            max_instances=1,
        )

        self.scheduler.start()
        logger.info(
            f"[RadarScheduler] Started. "
            f"Pipeline: every {RADAR_SCHEDULER_INTERVAL_MINUTES} min | "
            f"Free batch: daily at {RADAR_FREE_RELEASE_HOUR_UTC}:00 UTC"
        )

    async def stop(self) -> None:
        """Gracefully stop scheduler and close all scraper HTTP clients."""
        self.scheduler.shutdown(wait=True)
        logger.info("[RadarScheduler] APScheduler stopped.")

        await asyncio.gather(
            self.arxiv_scraper.close(),
            self.hf_scraper.close(),
            self.blog_scraper.close(),
        )
        logger.info("[RadarScheduler] All scraper clients closed.")

    # -----------------------------------------------------------------------
    # DB helpers
    # -----------------------------------------------------------------------

    async def _insert_items(self, items: list[dict]) -> list[dict]:
        """
        Insert processed items into content_items table.

        Assigns UUIDs in Python before insert so the summarizer has IDs
        without relying on the DB returning rows.
        Uses upsert on source_url — silently skips duplicates.

        Returns items with 'id' field populated. Returns [] on failure.
        """
        if not items:
            return []

        try:
            # Assign UUIDs in Python — avoids needing DB to return them
            for item in items:
                item["id"] = str(uuid.uuid4())

            db = await get_service_client()
            await (
                db.table("content_items")
                .upsert(items, on_conflict="source_url")
                .execute()
            )

            logger.info(f"[RadarScheduler] Inserted {len(items)} items into DB.")
            return items

        except Exception as e:
            logger.error(
                f"[RadarScheduler] DB insert failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

    # -----------------------------------------------------------------------
    # Job 1: 30-minute pipeline cycle
    # -----------------------------------------------------------------------

    async def pipeline_cycle(self) -> None:
        """
        Full Radar pipeline cycle — runs every 30 minutes.

        Steps:
          1. Scrape all 3 sources in parallel
          2. In-memory dedup by source_url
          3. Processor (topic, difficulty, attention score, signal label, key_tags, DB dedup)
          4. Insert new items into DB
          5. Summarizer (LLM: summary + why_it_matters per item)
        """
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"[RadarScheduler] Cycle starting at {cycle_start.isoformat()}")

        try:
            # arXiv only publishes on weekdays at ~6AM UTC.
            # Skip arXiv on weekends (sat=5, sun=6) and outside the 6-8AM UTC window
            # to avoid wasted requests. RSS blogs + HF run every cycle regardless.
            weekday = cycle_start.weekday()  # 0=Mon ... 6=Sun
            arxiv_hour = cycle_start.hour
            should_scrape_arxiv = (
                weekday < 5 and  # Mon–Fri only
                6 <= arxiv_hour < 9  # 6–9AM UTC window (papers appear after 6AM)
            )
            if not should_scrape_arxiv:
                logger.info(
                    f"[RadarScheduler] Skipping arXiv "
                    f"(weekday={weekday}, hour={arxiv_hour}UTC — "
                    f"arXiv publishes weekdays 6-9AM UTC only)."
                )

            # Step 1: Scrape sources — arXiv conditional, others always
            scrape_tasks = []
            scrape_names = []
            if should_scrape_arxiv:
                scrape_tasks.append(self.arxiv_scraper.scrape())
                scrape_names.append("arXiv")
            scrape_tasks.append(self.hf_scraper.scrape())
            scrape_names.append("HuggingFace")
            scrape_tasks.append(self.blog_scraper.scrape())
            scrape_names.append("RSSBlogs")

            scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

            raw_items = []
            for name, result in zip(scrape_names, scrape_results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[RadarScheduler] {name} raised exception: "
                        f"{type(result).__name__}: {result}"
                    )
                else:
                    logger.info(f"[RadarScheduler] {name}: {len(result)} items scraped.")
                    raw_items.extend(result)

            if not raw_items:
                logger.warning("[RadarScheduler] No items from any scraper this cycle.")
                return

            # Step 2: In-memory dedup by source_url
            seen_urls = set()
            deduplicated = []
            for item in raw_items:
                url = item.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduplicated.append(item)

            logger.info(
                f"[RadarScheduler] {len(raw_items)} raw → "
                f"{len(deduplicated)} after in-memory dedup."
            )

            # Step 3: Process
            processed = await self.processor.process_items(deduplicated)
            if not processed:
                logger.info("[RadarScheduler] No new items after processing.")
                return

            # Step 4: Insert
            inserted = await self._insert_items(processed)
            if not inserted:
                logger.warning("[RadarScheduler] Insert failed — skipping summarization.")
                return

            # Step 5: Summarize
            summarized = await self.summarizer.summarize_batch(inserted)
            success_count = sum(1 for i in summarized if i.get("is_summarized"))

            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(
                f"[RadarScheduler] Cycle done in {elapsed:.1f}s | "
                f"Scraped: {len(raw_items)} | New: {len(processed)} | "
                f"Inserted: {len(inserted)} | Summarized: {success_count}"
            )

        except Exception as e:
            logger.error(
                f"[RadarScheduler] Unhandled exception in pipeline_cycle: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # Job 2: 4AM UTC free tier batch
    # -----------------------------------------------------------------------

    async def free_tier_batch(self) -> None:
        """
        Daily 4AM UTC job — releases top N items to free tier users.

        Selects top RADAR_FREE_DAILY_LIMIT summarized+unreleased items
        from the last 24 hours, ranked by attention_score.
        Marks them is_released=True + sets released_at timestamp.
        """
        logger.info("[RadarScheduler] 4AM free tier batch starting.")

        try:
            db = await get_service_client()

            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()

            resp = await (
                db.table("content_items")
                .select("id")
                .eq("is_released", False)
                .eq("is_summarized", True)
                .gte("fetched_at", cutoff)
                .order("attention_score", desc=True)
                .limit(RADAR_FREE_DAILY_LIMIT)
                .execute()
            )

            items = resp.data or []

            if not items:
                logger.info("[RadarScheduler] No unreleased items for free tier batch.")
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
                f"[RadarScheduler] Free tier batch done. Released {len(ids_to_release)} items."
            )

        except Exception as e:
            logger.error(
                f"[RadarScheduler] Free tier batch failed: {type(e).__name__}: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # Job 3: Daily email digest
    # -----------------------------------------------------------------------

    async def daily_digest_job(self) -> None:
        """
        Daily digest job — runs at RADAR_DIGEST_HOUR_UTC (default 8AM UTC).
        Sends top radar items to all subscribed + verified users via Resend.
        """
        logger.info("[RadarScheduler] Daily digest job triggered.")
        try:
            await self.digest_sender.send_daily_digests()
        except Exception as e:
            logger.error(
                f"[RadarScheduler] Daily digest job failed: {type(e).__name__}: {e}",
                exc_info=True,
            )

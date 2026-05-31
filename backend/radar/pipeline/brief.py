# radar/pipeline/brief.py
#
# Today's Brief assembly logic.
# Selects the best items from the last 24 hours with diversity caps.
# This is SEPARATE from the latest feeds (which are newest-first).
#
# Today's Brief = importance-first, curated, not congested.
# "A research analyst prepared this for me."

import datetime
import logging
from collections import defaultdict

from radar.core.database import get_service_client
from config import (
    BRIEF_MAX_PAPERS,
    BRIEF_MAX_MODELS,
    BRIEF_MAX_COMPANY_UPDATES,
    BRIEF_MAX_PER_TOPIC,
    BRIEF_MAX_PER_SOURCE,
)

logger = logging.getLogger("paperlens.radar.pipeline.brief")

# ---------------------------------------------------------------------------
# Fields returned for brief items (same as feed list — no full_content)
# ---------------------------------------------------------------------------
BRIEF_SELECT_FIELDS = (
    "id, title, summary, why_it_matters, source_url, source_name, "
    "content_type, authors, published_at, topic, difficulty, "
    "attention_score, signal_label, key_tags, is_summarized, "
    "has_peeler, fetched_at"
)


async def build_today_brief(plan: str = "pro") -> dict:
    """
    Build Today's Brief — curated, diversity-capped selection of best items.

    Selects from items published or fetched in the last 24 hours:
      - Top papers by attention_score (max BRIEF_MAX_PAPERS)
      - Top models by attention_score (max BRIEF_MAX_MODELS)
      - Top company updates by attention_score (max BRIEF_MAX_COMPANY_UPDATES)

    Diversity caps applied across ALL sections:
      - max BRIEF_MAX_PER_TOPIC items from the same topic
      - max BRIEF_MAX_PER_SOURCE items from the same source

    Free users get is_released=True items only.
    Pro users get all summarized items.

    Returns:
        {
            "papers":          [...],
            "models":          [...],
            "company_updates": [...],
            "total":           <int>,
            "generated_at":    "<ISO datetime>",
            "date_label":      "Today, May 29"
        }
    """
    try:
        db = await get_service_client()

        # Last 24 hours window
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        ).isoformat()

        # Base query — summarized items from last 24 hours
        base_query = (
            db.table("content_items")
            .select(BRIEF_SELECT_FIELDS)
            .eq("is_summarized", True)
            .gte("fetched_at", cutoff)
        )

        if plan == "free":
            base_query = base_query.eq("is_released", True)

        # Fetch more than we need — apply diversity caps in Python
        resp = await (
            base_query
            .order("attention_score", desc=True)
            .limit(200)   # fetch enough to apply diversity caps
            .execute()
        )

        all_items = resp.data or []

        if not all_items:
            logger.info("[Brief] No items found in last 24 hours.")
            return _empty_brief()

        # --- Apply diversity caps across all content types ---
        papers_pool   = [i for i in all_items if i.get("content_type") == "paper"]
        models_pool   = [i for i in all_items if i.get("content_type") == "model"]
        blogs_pool    = [i for i in all_items if i.get("content_type") == "blog_post"]

        # Shared diversity state across ALL sections
        topic_counts : dict[str, int] = defaultdict(int)
        source_counts: dict[str, int] = defaultdict(int)

        papers          = _select_diverse(papers_pool,   BRIEF_MAX_PAPERS,          topic_counts, source_counts)
        models          = _select_diverse(models_pool,   BRIEF_MAX_MODELS,          topic_counts, source_counts)
        company_updates = _select_diverse(blogs_pool,    BRIEF_MAX_COMPANY_UPDATES, topic_counts, source_counts)

        now = datetime.datetime.now(datetime.timezone.utc)
        date_label = now.strftime("Today, %b %-d")  # e.g. "Today, May 29"

        total = len(papers) + len(models) + len(company_updates)

        logger.info(
            f"[Brief] Built: {len(papers)} papers | "
            f"{len(models)} models | {len(company_updates)} company updates"
        )

        return {
            "papers":          papers,
            "models":          models,
            "company_updates": company_updates,
            "total":           total,
            "generated_at":    now.isoformat(),
            "date_label":      date_label,
        }

    except Exception as e:
        logger.error(f"[Brief] Error building brief: {type(e).__name__}: {e}", exc_info=True)
        return _empty_brief()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_diverse(
    pool: list[dict],
    max_items: int,
    topic_counts: dict,
    source_counts: dict,
) -> list[dict]:
    """
    Select up to max_items from pool applying shared diversity caps.

    pool is already sorted by attention_score DESC (from DB query).

    Caps enforced using shared topic_counts and source_counts dicts
    so diversity is maintained ACROSS sections (papers + models + blogs together).

    Rules:
      - max BRIEF_MAX_PER_TOPIC items from same topic (shared across sections)
      - max BRIEF_MAX_PER_SOURCE items from same source (shared across sections)
    """
    selected = []

    for item in pool:
        if len(selected) >= max_items:
            break

        topic  = item.get("topic") or "Other"
        source = item.get("source_name") or "Unknown"

        if topic_counts[topic] >= BRIEF_MAX_PER_TOPIC:
            continue
        if source_counts[source] >= BRIEF_MAX_PER_SOURCE:
            continue

        selected.append(item)
        topic_counts[topic]   += 1
        source_counts[source] += 1

    return selected


def _empty_brief() -> dict:
    """Return an empty brief structure when no items exist."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "papers":          [],
        "models":          [],
        "company_updates": [],
        "total":           0,
        "generated_at":    now.isoformat(),
        "date_label":      now.strftime("Today, %b %-d"),
    }

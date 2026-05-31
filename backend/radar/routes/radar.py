# radar/routes/radar.py
#
# Research Radar API routes — feed endpoints.
#
# Endpoints:
#   GET /api/radar/today        → Today's Brief (curated, diversity-capped)
#   GET /api/radar/papers       → Paginated papers feed
#   GET /api/radar/models       → Paginated models feed
#   GET /api/radar/companies    → Paginated company updates feed
#   GET /api/radar/stats        → Item counts for header display
#
# Auth: Supabase JWT (Bearer token) via get_current_user dependency.
# Plan gating: Free users see is_released=True items only.

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from radar.core.database import get_service_client, get_anon_client
from radar.pipeline.brief import build_today_brief
from radar.models import (
    BriefResponse, FeedResponse, StatsResponse,
    RadarItem,
)
from routes.auth import get_optional_user   # lenient: None if not logged in

logger = logging.getLogger("paperlens.radar.routes.radar")

# Rate limiter — shared instance imported by main.py
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/radar", tags=["Research Radar"])

# ---------------------------------------------------------------------------
# In-memory plan cache — avoids DB round-trip on every request
# ---------------------------------------------------------------------------
_plan_cache: dict[str, tuple[str, float]] = {}
PLAN_CACHE_TTL = 300   # 5 minutes

# ---------------------------------------------------------------------------
# Query param validation
# ---------------------------------------------------------------------------
VALID_SORT = {"attention", "newest"}
FEED_LIMIT  = 50

# DB select fields for feed lists (no full_content — too large)
FEED_SELECT = (
    "id, title, summary, why_it_matters, source_url, source_name, "
    "content_type, authors, published_at, fetched_at, topic, difficulty, "
    "attention_score, signal_label, key_tags, has_peeler, is_summarized, "
    "avg_rating, rating_count, ranking_score"
)
# Fallback if rating columns not yet migrated
FEED_SELECT_BASIC = (
    "id, title, summary, why_it_matters, source_url, source_name, "
    "content_type, authors, published_at, fetched_at, topic, difficulty, "
    "attention_score, signal_label, key_tags, has_peeler, is_summarized"
)


# ---------------------------------------------------------------------------
# Helper: get user plan (with cache)
# ---------------------------------------------------------------------------

async def _get_user_plan(user_id: str) -> str:
    """
    Look up user plan with 5-minute in-memory cache.
    Returns "free", "trial", or "pro". Defaults to "free" on any error.
    Guest users (unauthenticated) always get "free" — skip DB lookup.
    """
    # Guest / unauthenticated — don't hit DB
    if not user_id or user_id == "guest":
        return "free"

    now = time.time()
    if user_id in _plan_cache:
        cached_plan, cached_at = _plan_cache[user_id]
        if now - cached_at < PLAN_CACHE_TTL:
            return cached_plan

    try:
        db = await get_service_client()
        resp = await (
            db.table("user_preferences")
            .select("plan")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        plan = (
            resp.data[0].get("plan", "free")
            if resp.data
            else "free"
        )
    except Exception as e:
        logger.error(
            f"[Radar] Failed to fetch plan for {user_id}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        plan = "free"  # Never accidentally grant Pro

    _plan_cache[user_id] = (plan, now)
    return plan


# ---------------------------------------------------------------------------
# GET /api/radar/today — Today's Brief
# ---------------------------------------------------------------------------

@router.get("/today", response_model=BriefResponse)
@limiter.limit("60/minute")
async def get_today_brief(
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Return Today's Brief — curated, diversity-capped selection of best items
    from the last 24 hours.

    Sections:
      - papers:          top papers by attention_score (max 4)
      - models:          top models by attention_score (max 3)
      - company_updates: top blog posts by attention_score (max 3)

    Diversity caps applied:
      - max 4 items per topic across all sections
      - max 2 items per source across all sections

    Pro users see all summarized items.
    Free users see is_released=True items only.
    """
    user_id = (current_user or {}).get("sub", "guest")
    plan    = await _get_user_plan(user_id)

    brief = await build_today_brief(plan=plan)

    return BriefResponse(
        papers          = [RadarItem(**i) for i in brief["papers"]],
        models          = [RadarItem(**i) for i in brief["models"]],
        company_updates = [RadarItem(**i) for i in brief["company_updates"]],
        total           = brief["total"],
        generated_at    = brief["generated_at"],
        date_label      = brief["date_label"],
        plan            = plan,
    )


# ---------------------------------------------------------------------------
# Shared feed helper
# ---------------------------------------------------------------------------

async def _get_feed(
    content_type: str,
    plan: str,
    topic: Optional[str],
    sort: str,
    offset: int,
) -> list[dict]:
    """
    Fetch paginated feed for a specific content_type.

    sort="attention" → order by attention_score DESC (importance)
    sort="newest"    → order by published_at DESC

    Free users get is_released=True only.
    """
    try:
        db = await get_anon_client()

        query = (
            db.table("content_items")
            .select(FEED_SELECT)
            .eq("content_type", content_type)
            .eq("is_summarized", True)
        )

        if plan == "free":
            query = query.eq("is_released", True)

        if topic:
            query = query.eq("topic", topic)

        if sort == "newest":
            query = query.order("published_at", desc=True)
        else:
            # Default: community ranking (attention_score × 0.6 + avg_rating × 20 × 0.4)
            # Falls back to attention_score for unrated items (ranking_score = attention_score * 0.6)
            query = (
                query
                .order("ranking_score", desc=True)
                .order("fetched_at", desc=True)
            )

        query = query.range(offset, offset + FEED_LIMIT - 1)

        try:
            resp = await query.execute()
        except Exception:
            # Rating columns may not exist yet — fall back to basic select
            query_basic = (
                db.table("content_items")
                .select(FEED_SELECT_BASIC)
                .eq("content_type", content_type)
                .eq("is_summarized", True)
            )
            if plan == "free":
                query_basic = query_basic.eq("is_released", True)
            if topic:
                query_basic = query_basic.eq("topic", topic)
            if sort == "newest":
                query_basic = query_basic.order("published_at", desc=True)
            else:
                query_basic = query_basic.order("attention_score", desc=True).order("fetched_at", desc=True)
            query_basic = query_basic.range(offset, offset + FEED_LIMIT - 1)
            resp = await query_basic.execute()

        return resp.data or []

    except Exception as e:
        logger.error(f"[Radar] Feed error (type={content_type}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch feed.")


# ---------------------------------------------------------------------------
# GET /api/radar/papers
# ---------------------------------------------------------------------------

@router.get("/papers", response_model=FeedResponse)
@limiter.limit("100/minute")
async def get_papers_feed(
    request: Request,
    topic:  Optional[str] = Query(default=None, description="Filter by topic"),
    sort:   str           = Query(default="attention", description="'attention' or 'newest'"),
    offset: int           = Query(default=0, ge=0),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Paginated papers feed.
    Default sort: importance (attention_score).
    Option to sort by newest-first.
    Papers include difficulty + has_peeler flag for "Peel this paper" action.
    """
    if sort not in VALID_SORT:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort '{sort}'. Use 'attention' or 'newest'."
        )

    user_id = (current_user or {}).get("sub", "guest")
    plan    = await _get_user_plan(user_id)
    items   = await _get_feed("paper", plan, topic, sort, offset)

    logger.info(
        f"[Radar] papers user={user_id} plan={plan} topic={topic} "
        f"sort={sort} offset={offset} → {len(items)} items"
    )

    return FeedResponse(
        items    = [RadarItem(**i) for i in items],
        count    = len(items),
        offset   = offset,
        has_more = len(items) == FEED_LIMIT,
        plan     = plan,
    )


# ---------------------------------------------------------------------------
# GET /api/radar/models
# ---------------------------------------------------------------------------

@router.get("/models", response_model=FeedResponse)
@limiter.limit("100/minute")
async def get_models_feed(
    request: Request,
    topic:  Optional[str] = Query(default=None),
    sort:   str           = Query(default="attention"),
    offset: int           = Query(default=0, ge=0),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Paginated models feed (HuggingFace releases).
    Cards include pipeline_tag, likes, downloads from metadata_json
    (available on the detail endpoint GET /api/radar/item/{id}).
    """
    if sort not in VALID_SORT:
        raise HTTPException(status_code=400, detail=f"Invalid sort '{sort}'.")

    user_id = (current_user or {}).get("sub", "guest")
    plan    = await _get_user_plan(user_id)
    items   = await _get_feed("model", plan, topic, sort, offset)

    logger.info(
        f"[Radar] models user={user_id} plan={plan} sort={sort} → {len(items)} items"
    )

    return FeedResponse(
        items    = [RadarItem(**i) for i in items],
        count    = len(items),
        offset   = offset,
        has_more = len(items) == FEED_LIMIT,
        plan     = plan,
    )


# ---------------------------------------------------------------------------
# GET /api/radar/companies
# ---------------------------------------------------------------------------

@router.get("/companies", response_model=FeedResponse)
@limiter.limit("100/minute")
async def get_companies_feed(
    request: Request,
    sort:   str        = Query(default="attention"),
    offset: int        = Query(default=0, ge=0),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Paginated company updates feed (blog posts from AI labs).
    Shows: company name, announcement title, summary, why it matters, link.
    """
    if sort not in VALID_SORT:
        raise HTTPException(status_code=400, detail=f"Invalid sort '{sort}'.")

    user_id = (current_user or {}).get("sub", "guest")
    plan    = await _get_user_plan(user_id)
    items   = await _get_feed("blog_post", plan, None, sort, offset)

    logger.info(
        f"[Radar] companies user={user_id} plan={plan} → {len(items)} items"
    )

    return FeedResponse(
        items    = [RadarItem(**i) for i in items],
        count    = len(items),
        offset   = offset,
        has_more = len(items) == FEED_LIMIT,
        plan     = plan,
    )


# ---------------------------------------------------------------------------
# GET /api/radar/stats — header stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=StatsResponse)
@limiter.limit("60/minute")
async def get_radar_stats(
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Stats for the Radar header:
      - scanned_today: total items fetched in last 24h
      - high_signal: items with signal_label = 'High Signal' today
      - by_type: counts by content_type
      - by_topic: counts by topic

    Used by: "42 updates scanned • 12 high-signal items found" status line.
    """
    import datetime

    user_id = (current_user or {}).get("sub", "guest")
    plan    = await _get_user_plan(user_id)

    try:
        db = await get_service_client()

        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        ).isoformat()

        # scanned_today counts ALL items fetched today (summarized or not — it's a scrape count)
        # The feeds themselves still filter by is_summarized=True
        query = (
            db.table("content_items")
            .select("content_type, topic, signal_label")
            .gte("fetched_at", cutoff)
            .limit(5000)
        )

        resp = await query.execute()
        rows = resp.data or []

        by_type: dict[str, int]  = {}
        by_topic: dict[str, int] = {}
        high_signal = 0

        for row in rows:
            ct = row.get("content_type") or "unknown"
            by_type[ct] = by_type.get(ct, 0) + 1

            topic = row.get("topic") or "Other"
            by_topic[topic] = by_topic.get(topic, 0) + 1

            if row.get("signal_label") == "High Signal":
                high_signal += 1

        return StatsResponse(
            scanned_today = len(rows),
            high_signal   = high_signal,
            by_type       = by_type,
            by_topic      = by_topic,
        )

    except Exception as e:
        logger.error(f"[Radar] Stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch stats.")

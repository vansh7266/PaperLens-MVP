# routes/feed.py

import logging
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.database import get_anon_client, get_service_client
from routes.auth import get_current_user  # shared JWT dependency (built in Phase 10)
import time

logger = logging.getLogger("paperlens.routes.feed")

# In-memory plan cache — avoids DB call on every request
# Key: user_id, Value: (plan_string, cached_at_timestamp)
_plan_cache: dict[str, tuple[str, float]] = {}
PLAN_CACHE_TTL_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Rate limiter — 100 requests per minute per IP
# Limiter instance is created here; registered on the FastAPI app in main.py
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/feed", tags=["feed"])

# ---------------------------------------------------------------------------
# Valid filter values — used for Pydantic + query param validation
# ---------------------------------------------------------------------------
VALID_TYPES = {"all", "papers", "models", "blogs"}
VALID_TOPICS = {"LLMs", "CV", "RL", "NLP", "Multimodal", "Generative_AI", "General_AI"}

# Map URL param values to content_items.content_type values in DB
TYPE_TO_DB = {
    "papers": "paper",
    "models": "model",
    "blogs":  "blog_post",
}

# Max items returned per request
FEED_LIMIT = 50


# ---------------------------------------------------------------------------
# Pydantic response models — define exactly what the API returns
# Prevents leaking internal fields (e.g. metadata_json internals)
# ---------------------------------------------------------------------------

class FeedItem(BaseModel):
    """Single item in the feed response."""
    id: str
    title: str
    summary: Optional[str]
    source_url: str
    source_name: str
    content_type: str
    authors: Optional[list[str]]
    published_at: Optional[str]
    topic: Optional[str]
    difficulty: Optional[str]
    attention_score: Optional[float]
    is_summarized: bool
    fetched_at: Optional[str]

    class Config:
        # Allow extra fields from DB row — we only expose what's in this model
        extra = "ignore"


class FeedResponse(BaseModel):
    """Top-level feed response envelope."""
    items: list[FeedItem]
    count: int
    plan: str  # "free" or "pro" — useful for frontend to know which tier is active
    offset: int  # ADD THIS


class StatsResponse(BaseModel):
    """Sidebar stats — counts by topic and content type."""
    by_topic: dict[str, int]
    by_type: dict[str, int]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_plan(user_id: str) -> str:
    """
    Look up user's plan with 5-minute in-memory cache.
    Prevents a DB call on every feed request.
    """
    now = time.time()

    # Return cached value if still fresh
    if user_id in _plan_cache:
        cached_plan, cached_at = _plan_cache[user_id]
        if now - cached_at < PLAN_CACHE_TTL_SECONDS:
            return cached_plan

    # Cache miss or expired — fetch from DB
    try:
        db = await get_service_client()
        response = await (
            db.table("user_preferences")
            .select("plan")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        plan = response.data[0].get("plan", "free") if response.data else "free"

    except Exception as e:
        logger.error(
            f"[Feed] Failed to fetch plan for user {user_id}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        plan = "free"  # Default to free on error — never accidentally grant Pro

    # Store in cache
    _plan_cache[user_id] = (plan, now)
    return plan


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=FeedResponse)
@limiter.limit("100/minute")
async def get_feed(
    request: Request,
    type: Optional[str] = Query(default="all", description="Filter by content type"),
    topic: Optional[str] = Query(default=None, description="Filter by topic"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    current_user: dict = Depends(get_current_user),
):
    """
    Return paginated feed for the authenticated user.

    Pro users: all summarized items, ordered by attention_score.
    Free users: only is_released=True items (set by 4AM batch).

    Query params:
        type:  "all" | "papers" | "models" | "blogs"
        topic: "LLMs" | "CV" | "RL" | "NLP" | "Multimodal" | "Generative_AI" | "General_AI"
    """
    # --- Input validation ---
    if type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type}'. Must be one of: {', '.join(VALID_TYPES)}"
        )

    if topic and topic not in VALID_TOPICS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid topic '{topic}'. Must be one of: {', '.join(VALID_TOPICS)}"
        )

    user_id = current_user["sub"]  # Supabase JWT puts user UUID in "sub" claim

    # --- Get user plan ---
    plan = await _get_user_plan(user_id)

    try:
        db = await get_anon_client()  # Anon client — respects RLS

        # --- Build query ---
        # Select only fields defined in FeedItem — no full_content (too large for list view)
        query = (
            db.table("content_items")
            .select(
                "id, title, summary, source_url, source_name, content_type, "
                "authors, published_at, topic, difficulty, attention_score, "
                "is_summarized, fetched_at"
            )
            .eq("is_summarized", True)   # Only show items with summaries
        )

        # --- Plan-based filtering ---
        if plan == "free":
            # Free users see only items released by 4AM batch
            query = query.eq("is_released", True)
        # Pro users: no is_released filter — see everything summarized

        # --- Type filter ---
        if type != "all":
            db_type = TYPE_TO_DB[type]   # e.g. "papers" → "paper"
            query = query.eq("content_type", db_type)

        # --- Topic filter ---
        if topic:
            query = query.eq("topic", topic)

        # --- Ordering + limit ---
        query = (
            query
            .order("attention_score", desc=True)
            .order("fetched_at", desc=True)
            .range(offset, offset + FEED_LIMIT - 1)
        )

        response = await query.execute()
        items = response.data or []

        logger.info(
            f"[Feed] user={user_id} plan={plan} type={type} topic={topic} "
            f"→ {len(items)} items"
        )

        return FeedResponse(
            items=[FeedItem(**item) for item in items],
            count=len(items),
            plan=plan,
            offset=offset,  # ADD THIS
        )

    except Exception as e:
        logger.error(
            f"[Feed] Error fetching feed for user {user_id}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch feed.")


@router.get("/stats", response_model=StatsResponse)
@limiter.limit("100/minute")
async def get_feed_stats(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Return item counts by topic and content type for the sidebar.

    Example response:
        {
            "by_topic": {"LLMs": 15, "CV": 8, "RL": 3},
            "by_type":  {"paper": 20, "model": 4, "blog_post": 2},
            "total": 26
        }
    """
    user_id = current_user["sub"]
    plan = await _get_user_plan(user_id)

    try:
        db = await get_anon_client()

        # Base query — same plan filter as feed
        query = (
            db.table("content_items")
            .select("topic, content_type")
            .eq("is_summarized", True)
            .limit(5000)
        )

        if plan == "free":
            query = query.eq("is_released", True)

        response = await query.execute()
        rows = response.data or []

        # Aggregate counts in Python — simpler than PostgREST GROUP BY
        by_topic: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for row in rows:
            # Count by topic
            t = row.get("topic") or "General_AI"
            by_topic[t] = by_topic.get(t, 0) + 1

            # Count by content type
            ct = row.get("content_type") or "unknown"
            by_type[ct] = by_type.get(ct, 0) + 1

        return StatsResponse(
            by_topic=by_topic,
            by_type=by_type,
            total=len(rows),
        )

    except Exception as e:
        logger.error(
            f"[Feed] Stats error for user {user_id}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch stats.")
# routes/news.py

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.database import get_anon_client
from routes.feed import _get_user_plan, limiter
from routes.auth import get_current_user

logger = logging.getLogger("paperlens.routes.news")

router = APIRouter(prefix="/api/feed", tags=["news"])


# ---------------------------------------------------------------------------
# Pydantic response model — full item detail (all DB fields)
# Feed list returns FeedItem (partial); this returns everything
# ---------------------------------------------------------------------------

class NewsDetail(BaseModel):
    """
    Full detail view of a single content item.

    Includes full_content (abstract/article body) and metadata_json
    which are omitted from the feed list for bandwidth reasons.
    """
    id: str
    title: str
    summary: Optional[str]
    source_url: str
    source_name: str
    content_type: str
    arxiv_id: Optional[str]
    authors: Optional[list[str]]
    published_at: Optional[str]
    fetched_at: Optional[str]
    topic: Optional[str]
    difficulty: Optional[str]
    attention_score: Optional[float]
    full_content: Optional[str]      # Abstract or article body — not in list view
    metadata_json: Optional[dict]    # Source-specific data (category, tags, etc.)
    is_summarized: bool
    is_released: bool
    has_peeler: bool
    peel_count: int

    class Config:
        extra = "ignore"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/{id}", response_model=NewsDetail)
@limiter.limit("100/minute")
async def get_news_detail(
    id: str,
    request: Request,                               # Required by slowapi
    current_user: dict = Depends(get_current_user), # JWT auth
):
    """
    Return full detail for a single content item.

    Access rules:
      - Pro users: can access any summarized item regardless of is_released
      - Free users: can only access is_released=True items
        → 403 if item exists but is unreleased (not 404 — avoids leaking existence)

    Args:
        id: Supabase UUID of the content item

    Returns:
        Full NewsDetail with all fields including full_content and metadata_json
    """
    user_id = current_user["sub"]
    plan = await _get_user_plan(user_id)

    try:
        db = await get_anon_client()

        # Fetch the item by ID — all fields
        response = await (
            db.table("content_items")
            .select("*")
            .eq("id", id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        # --- 404: item doesn't exist at all ---
        if not rows:
            logger.info(f"[News] Item not found: id={id} user={user_id}")
            raise HTTPException(status_code=404, detail="Item not found.")

        item = rows[0]

        # --- 403: item exists but free user can't access it yet ---
        # We return 403 (not 404) so the frontend knows the item exists
        # but is gated — can show "Available with Pro" instead of "Not found"
        if plan == "free" and not item.get("is_released", False):
            logger.info(
                f"[News] Free user blocked from unreleased item: "
                f"id={id} user={user_id}"
            )
            raise HTTPException(
                status_code=403,
                detail="This item is not yet available on the free tier."
            )

        logger.info(f"[News] Returning detail: id={id} user={user_id} plan={plan}")
        return NewsDetail(**item)

    except HTTPException:
        # Re-raise HTTP exceptions (404, 403) — don't swallow them
        raise

    except Exception as e:
        logger.error(
            f"[News] Error fetching item {id} for user {user_id}: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch item.")
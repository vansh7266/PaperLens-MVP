# radar/routes/rating.py
#
# Community rating endpoints.
#
# Endpoints:
#   POST /api/radar/rate/{item_id}   → submit or update a 1-5 star rating
#   GET  /api/radar/rate/{item_id}   → get current user's rating for an item
#
# Rating is open to all users (free + pro) — community engagement.
# One rating per user per item; re-rating updates the score.
# avg_rating and ranking_score updated atomically via SQL function.

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from radar.core.database import get_service_client
from routes.auth import get_current_user, get_optional_user

logger = logging.getLogger("paperlens.radar.routes.rating")
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/radar", tags=["Ratings"])


class RateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="1–5 star rating")


class RateResponse(BaseModel):
    item_id: str
    your_rating: int
    avg_rating: float
    rating_count: int


# ---------------------------------------------------------------------------
# POST /api/radar/rate/{item_id}
# ---------------------------------------------------------------------------

@router.post("/rate/{item_id}", response_model=RateResponse)
@limiter.limit("60/minute")
async def submit_rating(
    item_id: str,
    body: RateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit or update a 1-5 star rating for a Radar item.
    Re-rating updates the score (no duplicate rows).
    Updates avg_rating and ranking_score atomically via SQL RPC.
    """
    user_id = current_user["sub"]

    try:
        db = await get_service_client()

        # Verify item exists
        item = await db.table("content_items").select("id").eq("id", item_id).limit(1).execute()
        if not item.data:
            raise HTTPException(status_code=404, detail="Item not found.")

        # Upsert via SQL function (atomic: update rating + recalculate avg)
        result = await db.rpc("upsert_rating", {
            "p_user_id": user_id,
            "p_item_id": item_id,
            "p_rating":  body.rating,
        }).execute()

        row = result.data[0] if result.data else {}

        return RateResponse(
            item_id=item_id,
            your_rating=body.rating,
            avg_rating=round(row.get("avg_rating", body.rating), 2),
            rating_count=row.get("rating_count", 1),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Rating] Failed for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit rating.")


# ---------------------------------------------------------------------------
# GET /api/radar/rate/{item_id}
# ---------------------------------------------------------------------------

@router.get("/rate/{item_id}")
@limiter.limit("120/minute")
async def get_my_rating(
    item_id: str,
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Get the current user's rating for an item (if authenticated).
    Also returns the item's avg_rating and rating_count for display.
    """
    try:
        db = await get_service_client()

        # Get item's aggregate rating
        item = await db.table("content_items")\
            .select("avg_rating, rating_count")\
            .eq("id", item_id).limit(1).execute()

        if not item.data:
            raise HTTPException(status_code=404, detail="Item not found.")

        row = item.data[0]
        avg = round(row.get("avg_rating") or 0.0, 2)
        count = row.get("rating_count") or 0
        your_rating = None

        # If user is logged in, fetch their specific rating
        if current_user:
            r = await db.table("ratings")\
                .select("rating")\
                .eq("user_id", current_user["sub"])\
                .eq("item_id", item_id)\
                .limit(1).execute()
            if r.data:
                your_rating = r.data[0]["rating"]

        return {
            "item_id": item_id,
            "your_rating": your_rating,
            "avg_rating": avg,
            "rating_count": count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Rating] GET failed for {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch rating.")

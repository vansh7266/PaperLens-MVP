# radar/routes/saved.py
#
# Saved items + read tracking routes.
#
# Endpoints:
#   GET    /api/radar/saved          → user's reading queue
#   POST   /api/radar/save/{id}      → save an item
#   DELETE /api/radar/save/{id}      → unsave an item
#   POST   /api/radar/read/{id}      → mark item as read

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from radar.core.database import get_service_client
from radar.models import (
    SavedResponse, SaveActionResponse, ReadActionResponse,
    SavedItem, RadarItem,
)
from routes.auth import get_current_user
from radar.routes.radar import _get_user_plan

logger = logging.getLogger("paperlens.radar.routes.saved")
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/radar", tags=["Saved Items"])

SAVED_SELECT = (
    "id, title, summary, why_it_matters, source_url, source_name, "
    "content_type, authors, published_at, fetched_at, topic, difficulty, "
    "attention_score, signal_label, key_tags, has_peeler, is_summarized"
)


# ---------------------------------------------------------------------------
# GET /api/radar/saved
# ---------------------------------------------------------------------------

@router.get("/saved", response_model=SavedResponse)
@limiter.limit("60/minute")
async def get_saved_items(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Return the user's saved reading queue.

    Items are ordered by saved_at DESC (most recently saved first).
    The full RadarItem is embedded in each SavedItem — no extra fetches needed.
    """
    user_id = current_user["sub"]
    plan    = await _get_user_plan(user_id)

    try:
        db = await get_service_client()

        # Fetch saved_items joined with content_items
        # Supabase PostgREST supports embedded selects via foreign keys
        resp = await (
            db.table("saved_items")
            .select(f"id, item_id, saved_at, content_items({SAVED_SELECT})")
            .eq("user_id", user_id)
            .order("saved_at", desc=True)
            .limit(200)
            .execute()
        )

        rows = resp.data or []

        saved_items = []
        for row in rows:
            item_data = row.get("content_items") or {}
            if not item_data:
                continue

            saved_items.append(SavedItem(
                id       = row["id"],
                item_id  = row["item_id"],
                saved_at = row["saved_at"],
                item     = RadarItem(**item_data),
            ))

        logger.info(f"[Saved] user={user_id} → {len(saved_items)} saved items")

        return SavedResponse(
            items = saved_items,
            count = len(saved_items),
            plan  = plan,
        )

    except Exception as e:
        logger.error(f"[Saved] Error fetching saved for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch saved items.")


# ---------------------------------------------------------------------------
# POST /api/radar/save/{item_id}
# ---------------------------------------------------------------------------

@router.post("/save/{item_id}", response_model=SaveActionResponse)
@limiter.limit("60/minute")
async def save_item(
    item_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Save a content item to the user's reading queue.

    Returns 200 with saved=True if successful.
    Returns 200 with saved=False if already saved (idempotent — no error).

    Plan limits: FREE_SAVED_LIMIT (20), Pro = unlimited.
    """
    user_id = current_user["sub"]
    plan    = await _get_user_plan(user_id)

    try:
        db = await get_service_client()

        # --- Check item exists ---
        item_check = await (
            db.table("content_items")
            .select("id")
            .eq("id", item_id)
            .limit(1)
            .execute()
        )
        if not item_check.data:
            raise HTTPException(status_code=404, detail="Item not found.")

        # --- Check plan limits (free users capped at 20 saved items) ---
        if plan == "free":
            from config import FREE_SAVED_LIMIT
            count_resp = await (
                db.table("saved_items")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            current_count = count_resp.count or 0
            if current_count >= FREE_SAVED_LIMIT:
                raise HTTPException(
                    status_code=403,
                    detail=f"Free plan allows up to {FREE_SAVED_LIMIT} saved items. "
                           f"Upgrade to Pro for unlimited saves."
                )

        # --- Check already saved (idempotent) ---
        existing = await (
            db.table("saved_items")
            .select("id")
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .limit(1)
            .execute()
        )

        if existing.data:
            return SaveActionResponse(
                saved   = True,
                item_id = item_id,
                message = "Already saved.",
            )

        # --- Insert saved item ---
        await (
            db.table("saved_items")
            .insert({"user_id": user_id, "item_id": item_id})
            .execute()
        )

        # --- Increment save_count on item ---
        await (
            db.rpc("increment_save_count", {"item_uuid": item_id})
            .execute()
        )

        logger.info(f"[Saved] user={user_id} saved item={item_id}")

        return SaveActionResponse(
            saved   = True,
            item_id = item_id,
            message = "Saved to reading queue.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Saved] Error saving item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save item.")


# ---------------------------------------------------------------------------
# DELETE /api/radar/save/{item_id}
# ---------------------------------------------------------------------------

@router.delete("/save/{item_id}", response_model=SaveActionResponse)
@limiter.limit("60/minute")
async def unsave_item(
    item_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Remove an item from the user's reading queue.
    Idempotent — returns 200 even if item was not saved.
    """
    user_id = current_user["sub"]

    try:
        db = await get_service_client()

        # Check if it exists first (to know if we need to decrement)
        existing = await (
            db.table("saved_items")
            .select("id")
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .limit(1)
            .execute()
        )

        if not existing.data:
            return SaveActionResponse(
                saved   = False,
                item_id = item_id,
                message = "Item was not saved.",
            )

        await (
            db.table("saved_items")
            .delete()
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .execute()
        )

        # Decrement save_count (floor at 0)
        await (
            db.rpc("decrement_save_count", {"item_uuid": item_id})
            .execute()
        )

        logger.info(f"[Saved] user={user_id} unsaved item={item_id}")

        return SaveActionResponse(
            saved   = False,
            item_id = item_id,
            message = "Removed from reading queue.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Saved] Error unsaving item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unsave item.")


# ---------------------------------------------------------------------------
# POST /api/radar/read/{item_id}
# ---------------------------------------------------------------------------

@router.post("/read/{item_id}", response_model=ReadActionResponse)
@limiter.limit("60/minute")
async def mark_read(
    item_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Mark a content item as read by this user.
    Idempotent — safe to call multiple times.
    Increments the global read_count on the item.
    """
    user_id = current_user["sub"]

    try:
        db = await get_service_client()

        # Check item exists
        item_check = await (
            db.table("content_items")
            .select("id")
            .eq("id", item_id)
            .limit(1)
            .execute()
        )
        if not item_check.data:
            raise HTTPException(status_code=404, detail="Item not found.")

        # Check already marked read
        existing = await (
            db.table("read_items")
            .select("id")
            .eq("user_id", user_id)
            .eq("item_id", item_id)
            .limit(1)
            .execute()
        )

        if not existing.data:
            # Insert read record
            await (
                db.table("read_items")
                .insert({"user_id": user_id, "item_id": item_id})
                .execute()
            )
            # Increment global read_count
            await (
                db.rpc("increment_read_count", {"item_uuid": item_id})
                .execute()
            )
            logger.debug(f"[Read] user={user_id} read item={item_id}")

        return ReadActionResponse(
            marked_read = True,
            item_id     = item_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Saved] Error marking read {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to mark as read.")

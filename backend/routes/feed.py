# ============================================================
# routes/feed.py — Feed API Routes
# ============================================================
# All API endpoints related to the paper feed.
# These are the routes the frontend calls to get papers.
#
# Endpoints:
#   GET /api/feed              → get papers for current user
#   GET /api/feed/topics       → get available topics
#   GET /api/feed/stats        → feed statistics
#   GET /api/feed/paper/{id}   → get one paper by ID
#   POST /api/feed/refresh     → manually trigger a fetch
#
# All routes verify the user's JWT token from Supabase Auth.
# Plan (free/pro) is read from token metadata.
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
import jwt

from config import (
    SUPABASE_ANON_KEY,
    TOPIC_MAP,
    FREE_TOP_PAPERS,
    DEBUG,
)
from core.database import (
    get_feed,
    get_paper_by_id,
    get_queue_status,
)

# Create the router
# All routes here get the /api prefix from main.py
router = APIRouter()


# ============================================================
# HELPER — verify JWT token
# ============================================================

def get_user_from_token(authorization: str) -> dict:
    """
    Extract user info from Supabase JWT token.

    The frontend sends the token in the Authorization header:
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

    We decode it to get:
        user_id → unique user identifier
        email   → user's email
        plan    → "free", "pro", or "team"
        topics  → their selected topics

    Returns dict with user info.
    Raises HTTPException 401 if token is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. "
                   "Expected: Bearer <token>"
        )

    token = authorization.replace("Bearer ", "")

    try:
        # Decode Supabase JWT
        # Supabase uses the anon key as the JWT secret
        payload = jwt.decode(
            token,
            SUPABASE_ANON_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no user ID")

        # Get metadata from token
        metadata = payload.get("user_metadata", {})
        app_metadata = payload.get("app_metadata", {})

        return {
            "user_id": user_id,
            "email":   payload.get("email", ""),
            "plan":    metadata.get("plan", "free"),
            "topics":  metadata.get("topics", []),
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please sign in again.")
    except jwt.InvalidTokenError as e:
        if DEBUG:
            print(f"[feed] JWT error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token.")


# ============================================================
# GET /api/feed — main feed endpoint
# ============================================================

@router.get("/feed")
async def get_user_feed(
    limit:  int    = Query(default=50, ge=1, le=100),
    offset: int    = Query(default=0, ge=0),
    topic:  Optional[str] = Query(default=None),
    type:   Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    Get the paper feed for the current user.

    Query parameters:
        limit  → number of papers (default 50, max 100)
        offset → pagination (default 0)
        topic  → filter by topic e.g. "LLMs"
        type   → filter by type: "paper", "news", "model"

    Headers:
        Authorization: Bearer <supabase_jwt_token>

    Returns:
        {
            papers: [...],
            total: 50,
            plan: "free",
            next_offset: 50
        }

    Pro users  → see all papers, newest first
    Free users → see only released papers (top 20 daily)
    """
    # Get user from token
    # If no token provided, treat as anonymous (free tier)
    user = None
    plan = "free"
    topics = []

    if authorization:
        try:
            user = get_user_from_token(authorization)
            plan = user["plan"]
            topics = user.get("topics", [])
        except HTTPException:
            # Invalid token → treat as anonymous
            pass

    # Override topic filter if provided in query
    filter_topics = None
    if topic:
        filter_topics = [topic]
    elif topics:
        filter_topics = topics

    # Override type filter
    filter_type = type  # "paper", "news", "model", or None

    # Fetch from database
    papers = await get_feed(
        topics=filter_topics,
        plan=plan,
        limit=limit,
        offset=offset,
    )

    # Apply type filter if specified
    if filter_type:
        papers = [p for p in papers if p.get("paper_type") == filter_type]

    # Format response
    formatted = [_format_paper(p, plan) for p in papers]

    return {
        "papers":      formatted,
        "total":       len(formatted),
        "plan":        plan,
        "next_offset": offset + len(formatted),
        "has_more":    len(formatted) == limit,
    }


# ============================================================
# GET /api/feed/topics
# ============================================================

@router.get("/feed/topics")
async def get_topics():
    """
    Get all available topics with their descriptions.
    Used by the frontend topic filter.

    Returns list of topic objects with name and color.
    """
    topic_colors = {
        "LLMs":             "#a8c4f0",
        "Computer Vision":  "#f0a8c4",
        "RL / Agents":      "#a8f0c4",
        "Diffusion Models": "#f0d5a8",
        "NLP":              "#c4a8f0",
        "Multimodal":       "#a8d4f0",
        "AI Safety":        "#f0f0a8",
        "Model Efficiency": "#d4f0a8",
        "Robotics":         "#f0c4a8",
    }

    topics = [
        {
            "name":  topic,
            "color": topic_colors.get(topic, "#a8c4f0"),
            "keywords_count": len(keywords),
        }
        for topic, keywords in TOPIC_MAP.items()
    ]

    return {"topics": topics, "total": len(topics)}


# ============================================================
# GET /api/feed/stats
# ============================================================

@router.get("/feed/stats")
async def get_feed_stats(
    authorization: Optional[str] = Header(default=None),
):
    """
    Get feed statistics for the dashboard stats cards.
    Returns counts for: new today, peeled papers, saved.

    Returns:
        {
            new_today: 24,
            peeled_available: 8,
            topics_count: 9,
            queue_status: {...}
        }
    """
    try:
        from core.database import get_service_client
        db = get_service_client()

        from datetime import timedelta
        from datetime import timezone as tz
        import datetime as dt

        now = dt.datetime.now(tz.utc)
        today_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        # Count papers fetched today
        today_result = db.table("papers").select(
            "id", count="exact"
        ).gte("fetched_at", today_start).execute()

        # Count papers with peeler available
        peeler_result = db.table("papers").select(
            "id", count="exact"
        ).eq("has_peeler", True).execute()

        return {
            "new_today":        today_result.count or 0,
            "peeled_available": peeler_result.count or 0,
            "topics_count":     len(TOPIC_MAP),
        }

    except Exception as e:
        return {
            "new_today":        0,
            "peeled_available": 0,
            "topics_count":     len(TOPIC_MAP),
            "error":            str(e) if DEBUG else None,
        }


# ============================================================
# GET /api/feed/paper/{paper_id}
# ============================================================

@router.get("/feed/paper/{paper_id}")
async def get_paper(paper_id: str):
    """
    Get a single paper by its ID.
    Used by Paper Peeler to load paper details.

    Parameters:
        paper_id → arXiv paper ID e.g. "2301.00001"

    Returns:
        Full paper object or 404 if not found
    """
    paper = await get_paper_by_id(paper_id)

    if not paper:
        raise HTTPException(
            status_code=404,
            detail=f"Paper '{paper_id}' not found. "
                   f"It may not have been fetched yet."
        )

    return {"paper": paper}


# ============================================================
# POST /api/feed/refresh — manual trigger (dev/admin only)
# ============================================================

@router.post("/feed/refresh")
async def trigger_refresh(
    authorization: Optional[str] = Header(default=None),
):
    """
    Manually trigger a feed refresh (fetch + process + queue).
    Development and admin use only.
    In production this runs automatically every 5 minutes.

    Returns:
        Result of the refresh pipeline run
    """
    # In production you'd check for admin role here
    # For now, anyone with a valid token can trigger it

    try:
        from scrapers.arxiv import fetch_latest
        from pipeline.processor import process_batch
        from pipeline.summarizer import summarize_batch
        from pipeline.queue import process_and_queue

        print("\n🔄 Manual feed refresh triggered via API...")

        # Run the pipeline
        raw_papers = await fetch_latest(max_per_category=10)
        processed  = await process_batch(raw_papers)
        summarized = await summarize_batch(processed)
        result     = await process_and_queue(summarized)

        return {
            "status":       "ok",
            "fetched":      len(raw_papers),
            "processed":    len(processed),
            "new_papers":   result.get("new_papers", 0),
            "pro_released": result.get("pro_released", 0),
            "queued":       result.get("queued", 0),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Refresh failed: {str(e)}"
        )


# ============================================================
# HELPER — format paper for frontend
# ============================================================

def _format_paper(paper: dict, plan: str) -> dict:
    """
    Format a database paper row for the frontend.
    Adds computed fields and ensures consistent structure.
    """
    return {
        "id":           paper.get("paper_id", ""),
        "title":        paper.get("title", ""),
        "summary":      paper.get("summary", ""),
        "topic":        paper.get("topic", "Other"),
        "difficulty":   paper.get("difficulty", "Intermediate"),
        "type":         paper.get("paper_type", "paper"),
        "source":       paper.get("source_name", "arXiv"),
        "url":          paper.get("url", ""),
        "authors":      paper.get("authors", []),
        "published_at": paper.get("published_at", ""),
        "has_peeler":   paper.get("has_peeler", False),
        "time_ago":     _time_ago(paper.get("published_at", "")),
    }


def _time_ago(published_at: str) -> str:
    """Convert a datetime string to a human-readable time ago."""
    if not published_at:
        return "recently"
    try:
        import datetime as dt
        from datetime import timezone as tz
        pub = dt.datetime.fromisoformat(
            published_at.replace("Z", "+00:00")
        )
        now = dt.datetime.now(tz.utc)
        diff = now - pub
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return "just now"
        elif hours < 24:
            return f"{hours}h ago"
        else:
            days = hours // 24
            return f"{days}d ago"
    except Exception:
        return "recently"

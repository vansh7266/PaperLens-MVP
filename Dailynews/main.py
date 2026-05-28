# main.py

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env file FIRST — before any config imports read os.getenv()
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import config
from config import validate_config
from core.database import get_service_client, get_anon_client
from pipeline.scheduler import PipelineScheduler
from routes.feed import router as feed_router, limiter
from routes.news import router as news_router

# ---------------------------------------------------------------------------
# Logging — configured ONCE here at app level
# All modules use logging.getLogger("paperlens.xxx") and inherit this config
# Never call logging.basicConfig() in any other file
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paperlens.main")

# ---------------------------------------------------------------------------
# Scheduler instance — created at module level so lifespan can access it
# ---------------------------------------------------------------------------
scheduler = PipelineScheduler()


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event("startup"/"shutdown")
# asynccontextmanager: code before yield = startup, after yield = shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage app startup and shutdown.

    Startup:
      1. Validate all required env vars are set
      2. Pre-warm Supabase clients (avoid cold-start latency on first request)
      3. Start APScheduler (fires first pipeline cycle immediately)

    Shutdown:
      4. Stop scheduler gracefully (waits for running jobs)
      5. Close all scraper HTTP clients (release connection pools)
    """
    # --- STARTUP ---
    logger.info("=== PaperLens API starting up ===")

    # Step 1: Validate config — logs warnings for missing env vars
    validate_config()

    # Step 2: Pre-warm DB clients — creates singletons now, not on first request
    try:
        await get_service_client()
        await get_anon_client()
        logger.info("[Main] Supabase clients pre-warmed.")
    except Exception as e:
        # Log but don't crash — /health endpoint should still respond
        logger.error(f"[Main] Failed to pre-warm DB clients: {e}")

    # Step 3: Start scheduler (registers 30-min + 4AM jobs, fires immediately)
    scheduler.start()

    logger.info("=== PaperLens API ready ===")

    yield  # App runs here — handles all requests

    # --- SHUTDOWN ---
    logger.info("=== PaperLens API shutting down ===")

    # Step 4+5: Stop scheduler + close scraper clients
    await scheduler.stop()

    logger.info("=== PaperLens API shutdown complete ===")


# ---------------------------------------------------------------------------
# FastAPI app instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PaperLens API",
    description="AI research intelligence platform — daily feed of papers, models, and blogs.",
    version="0.1.0",
    lifespan=lifespan,
    # Disable docs in production via env var — keeps attack surface small
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "true").lower() == "true" else None,
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# Rate limiter — attach to app so slowapi can handle 429 responses
# ---------------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# CORS middleware
# Allows frontend (running on different origin) to call the API
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173"  # Default: local dev frontends
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS],
    allow_credentials=True,   # Required for Authorization header to be sent
    allow_methods=["GET", "POST"],  # Only methods we use — no PUT/DELETE exposed
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(feed_router)   # /api/feed, /api/feed/stats
app.include_router(news_router)   # /api/feed/{id}


# ---------------------------------------------------------------------------
# Health check — no auth, no rate limit, always 200
# Used by deployment platform (Railway, Render) to verify app is alive
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    """
    Lightweight health check endpoint.

    Returns 200 if the app is running.
    Does NOT check DB connectivity — keeps response fast and dependency-free.
    Deployment platforms ping this every 30s.
    """
    return {"status": "ok", "version": "0.1.0"}
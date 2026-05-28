# ============================================================
# main.py — PaperLens Backend Entry Point
# ============================================================
# This is the first file Python runs when you start the server.
# It creates the FastAPI app, sets up middleware, registers
# all routes, and starts background tasks.
#
# Run command:
#   uvicorn main:app --reload --port 8000
#
# Test it:
#   http://localhost:8000/          → API alive check
#   http://localhost:8000/health    → detailed health check
#   http://localhost:8000/docs      → auto API documentation
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

# Import our config — the master settings file
from config import (
    APP_NAME,
    APP_VERSION,
    FRONTEND_URL,
    DEBUG,
    HOST,
    PORT,
    FETCH_INTERVAL_MINUTES,
    ENABLE_FEED_SCHEDULER,
    validate_config,
    get_active_model,
    ACTIVE_LLM,
)


# ============================================================
# LIFESPAN — runs on startup and shutdown
# ============================================================
# This replaces the old @app.on_event("startup") pattern
# Everything inside runs ONCE when server starts
# Perfect place to: validate config, test connections,
# start background scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  🔬 {APP_NAME} API v{APP_VERSION} starting...")
    print(f"{'='*55}")

    # Step 1: Validate all required environment variables
    missing = validate_config()
    if missing:
        print(f"\n  ❌ Missing environment variables:")
        for key in missing:
            print(f"     - {key}")
        print(f"\n  ⚠️  Server starting with missing config.")
        print(f"     Some features will not work.\n")
    else:
        print(f"\n  ✅ All environment variables loaded")

    # Step 2: Show active settings
    print(f"  🤖 Active LLM     : {ACTIVE_LLM}")
    print(f"  📦 Active model   : {get_active_model()}")
    print(f"  🌐 Frontend URL   : {FRONTEND_URL}")
    print(f"  🐛 Debug mode     : {DEBUG}")

    # Step 3: Test database connection
    # (we add this in Phase 4 when database.py is ready)
    # from core.database import test_connection
    # db_ok = await test_connection()
    # print(f"  🗄️  Database       : {'✅ connected' if db_ok else '❌ failed'}")

    # Step 4: Start background scheduler
    if ENABLE_FEED_SCHEDULER:
        from pipeline.scheduler import start_scheduler
        start_scheduler()
        print(f"  ⏰ Scheduler      : ✅ started (every {FETCH_INTERVAL_MINUTES} min)")
    else:
        print("  ⏰ Scheduler      : disabled (set ENABLE_FEED_SCHEDULER=true)")

    print(f"\n  🚀 Server ready at http://{HOST}:{PORT}")
    print(f"  📖 API docs      at http://{HOST}:{PORT}/docs")
    print(f"{'='*55}\n")

    # Hand control to the app — server runs here
    yield

    # ── SHUTDOWN ─────────────────────────────────────────────
    # Runs when server is stopped (Ctrl+C)
    print(f"\n  👋 {APP_NAME} shutting down gracefully...\n")


# ============================================================
# CREATE FASTAPI APP
# ============================================================
# lifespan= connects our startup/shutdown logic above

app = FastAPI(
    title=f"{APP_NAME} API",
    description="Backend API for PaperLens — AI/ML research intelligence platform",
    version=APP_VERSION,
    docs_url="/docs",        # Swagger UI at /docs
    redoc_url="/redoc",      # ReDoc UI at /redoc
    lifespan=lifespan,
)


# ============================================================
# CORS MIDDLEWARE
# ============================================================
# CORS = Cross Origin Resource Sharing
#
# Problem without CORS:
#   Frontend on localhost:3000 tries to call backend on localhost:8000
#   Browser says "BLOCKED — different origin"
#   Nothing works
#
# Solution with CORS:
#   We tell the browser "yes, localhost:3000 is allowed"
#   Now frontend can call backend freely
#
# In production: replace localhost:3000 with your real domain
# e.g. "https://paperlens.com"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,                    # from config (localhost:3000)
        "http://localhost:3000",         # local dev
        "http://localhost:5173",         # Vite / python http.server preview
        "http://localhost:5500",         # VS Code Live Server
        "http://localhost:5501",         # alternate static server
        "http://127.0.0.1:3000",         # alternate local
        "http://127.0.0.1:5173",         # alternate preview
        "http://127.0.0.1:5500",         # alternate local
        "http://127.0.0.1:5501",         # alternate static server
    ],
    allow_credentials=True,             # allow cookies and auth headers
    allow_methods=["*"],                # allow GET, POST, PUT, DELETE etc.
    allow_headers=["*"],                # allow all headers
)


# ============================================================
# ROUTES — register all API routes here
# ============================================================
# Each feature has its own router file in routes/
# We add them here as we build each phase
#
# Pattern:
#   from routes.feed import router as feed_router
#   app.include_router(feed_router, prefix="/api", tags=["Feed"])
#
# This means:
#   A route defined as @router.get("/feed") in feed.py
#   becomes available at GET /api/feed
#
# ── Phase 4: Feed routes ────────────────────────────────────
from routes.feed import router as feed_router
app.include_router(feed_router, prefix="/api", tags=["Feed"])
#
# ── Phase 6: Peeler routes ──────────────────────────────────
from routes.peeler import router as peeler_router
app.include_router(peeler_router)
#
# ── Phase 7: Auth routes ────────────────────────────────────
# from routes.auth import router as auth_router
# app.include_router(auth_router, prefix="/api", tags=["Auth"])
#
# ── Phase 8: WhatsApp routes ────────────────────────────────
# from routes.whatsapp import router as whatsapp_router
# app.include_router(whatsapp_router, prefix="/api", tags=["WhatsApp"])
#
# ── Phase 9: Payment routes ─────────────────────────────────
# from routes.payments import router as payments_router
# app.include_router(payments_router, prefix="/api", tags=["Payments"])


# ============================================================
# CORE ROUTES — always available
# ============================================================

@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint — confirms the API is alive.
    Open http://localhost:8000/ in browser to test.
    """
    return {
        "message": f"{APP_NAME} API is running",
        "version": APP_VERSION,
        "docs": f"http://localhost:{PORT}/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Detailed health check endpoint.
    Used to monitor if the server is healthy.
    
    Returns status of:
    - API server itself
    - Active LLM provider
    - Database connection (added in Phase 4)
    - Scheduler status (added in Phase 3)
    """
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "llm": {
            "provider": ACTIVE_LLM,
            "model": get_active_model(),
        },
        # These will be added in Phase 3 and 4:
        # "database": "connected",
        # "scheduler": "running",
    }


@app.get("/config-check", tags=["Health"])
async def config_check():
    """
    Checks which environment variables are loaded.
    Only shows which are SET or MISSING — never shows actual values.
    Safe to call during development.
    """
    missing = validate_config()
    return {
        "status": "ok" if not missing else "incomplete",
        "missing_variables": missing,
        "active_llm": ACTIVE_LLM,
        "active_model": get_active_model(),
    }


# ============================================================
# RUN DIRECTLY
# ============================================================
# This block only runs when you do: python main.py
# When using uvicorn command, this block is ignored
#
# Usage:
#   python main.py
#   OR
#   uvicorn main:app --reload --port 8000  (recommended)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=True,    # auto-restart when code changes
    )

# main.py — PaperLens Backend Entry Point
#
# Run:  uvicorn main:app --reload --port 8000
# Docs: http://localhost:8000/docs

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import (
    ACTIVE_LLM,
    APP_NAME,
    APP_VERSION,
    DEBUG,
    FRONTEND_URL,
    HOST,
    PORT,
    RADAR_SCHEDULER_INTERVAL_MINUTES,
    get_active_model,
    validate_config,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  🔬 {APP_NAME} API v{APP_VERSION} starting...")
    print(f"{'='*55}")

    missing = validate_config()
    if missing:
        print(f"\n  ❌ Missing env vars: {', '.join(missing)}")
        print(f"  ⚠️  Some features will not work.\n")
    else:
        print(f"\n  ✅ All environment variables loaded")

    print(f"  🤖 Active LLM   : {ACTIVE_LLM}")
    print(f"  📦 Active model : {get_active_model()}")
    print(f"  🌐 Frontend URL : {FRONTEND_URL}")
    print(f"  🐛 Debug mode   : {DEBUG}")

    # Pre-warm Radar async DB clients
    from radar.core.database import get_anon_client as radar_anon, get_service_client as radar_svc
    try:
        await radar_svc()
        await radar_anon()
        print("  🗄️  Radar DB     : ✅ async clients ready")
    except Exception as e:
        print(f"  🗄️  Radar DB     : ⚠️  {e}")

    # Start Research Radar scheduler
    from radar.pipeline.scheduler import RadarScheduler
    radar_scheduler = RadarScheduler()
    radar_scheduler.start()
    print(f"  📡 Radar        : ✅ scheduler started ({RADAR_SCHEDULER_INTERVAL_MINUTES}min cycle)")

    print(f"\n  🚀 Ready at http://{HOST}:{PORT}")
    print(f"  📖 Docs  at http://{HOST}:{PORT}/docs")
    print(f"{'='*55}\n")

    yield

    # ── SHUTDOWN ─────────────────────────────────────────────
    await radar_scheduler.stop()
    print(f"\n  👋 {APP_NAME} shutting down...\n")


app = FastAPI(
    title=f"{APP_NAME} API",
    description="PaperLens — AI/ML research intelligence platform",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5500",
        "http://localhost:5501",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:5501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Paper Peeler routes ──────────────────────────────────────
from routes.peeler import router as peeler_router
app.include_router(peeler_router)

# ── Research Radar routes ────────────────────────────────────
from radar.routes.radar import limiter as radar_limiter, router as radar_router
from radar.routes.email import router as email_router
from radar.routes.rating import router as rating_router
from radar.routes.saved import router as saved_router

app.include_router(radar_router)
app.include_router(saved_router)
app.include_router(email_router)
app.include_router(rating_router)

app.state.limiter = radar_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/", tags=["Root"])
async def root():
    return {"app": APP_NAME, "version": APP_VERSION, "docs": f"http://localhost:{PORT}/docs"}


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "llm": {"provider": ACTIVE_LLM, "model": get_active_model()},
    }


@app.get("/config-check", tags=["Health"])
async def config_check():
    missing = validate_config()
    return {
        "status": "ok" if not missing else "incomplete",
        "missing_variables": missing,
        "active_llm": ACTIVE_LLM,
        "active_model": get_active_model(),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)

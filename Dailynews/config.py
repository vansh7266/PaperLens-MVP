# config.py

import os
import logging

logger = logging.getLogger("paperlens.config")

# ---------------------------------------------------------------------------
# LLM PROVIDER SWITCH
# Change this one value to switch the entire system between providers.
# "gemini" → Gemini 2.0 Flash (testing, cheaper)
# "claude" → Claude Haiku (production)
# ---------------------------------------------------------------------------
ACTIVE_LLM = os.getenv("ACTIVE_LLM", "gemini")

# ---------------------------------------------------------------------------
# API KEYS — all from environment, never hardcoded
# Set these in your .env file (loaded by python-dotenv in main.py)
# ---------------------------------------------------------------------------

# Gemini API key — required when ACTIVE_LLM = "gemini"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Anthropic API key — required when ACTIVE_LLM = "claude"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# HuggingFace API key — optional, increases rate limits
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# ---------------------------------------------------------------------------
# SUPABASE CONFIG
# ---------------------------------------------------------------------------

# Your Supabase project URL (e.g. https://xyz.supabase.co)
SUPABASE_URL = os.getenv("SUPABASE_URL")

# Anon key — safe for frontend, respects RLS
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Service role key — bypasses RLS, backend/pipeline only, NEVER expose to frontend
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# ---------------------------------------------------------------------------
# PIPELINE LIMITS
# ---------------------------------------------------------------------------

# Max characters of full_content sent to LLM for summarization
# Keeps token cost predictable — abstracts rarely exceed this
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "2000"))

# Max simultaneous LLM API calls during summarization batch
# Prevents rate limit errors — 5 is safe for Gemini free tier
MAX_CONCURRENT_SUMMARIES = int(os.getenv("MAX_CONCURRENT_SUMMARIES", "5"))

# ---------------------------------------------------------------------------
# SCHEDULER CONFIG
# ---------------------------------------------------------------------------

# How often the pipeline runs (minutes) — fetches new content
SCHEDULER_INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "30"))

# Hour (UTC) when free user batch is released
# 4 = 4:00 AM UTC — overnight processing, ready for morning
FREE_TIER_RELEASE_HOUR_UTC = int(os.getenv("FREE_TIER_RELEASE_HOUR_UTC", "4"))

# Max papers included in the free daily digest
FREE_TIER_DAILY_LIMIT = int(os.getenv("FREE_TIER_DAILY_LIMIT", "20"))

# ---------------------------------------------------------------------------
# LLM MODEL NAMES
# ---------------------------------------------------------------------------

# Gemini model used during testing
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Claude model used in production
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Max tokens LLM returns per summary — 2-3 sentences fits in 150 tokens
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "150"))

# ---------------------------------------------------------------------------
# STARTUP VALIDATION
# Warn loudly on startup if critical env vars are missing
# Doesn't crash — lets FastAPI start so /health endpoint still responds
# ---------------------------------------------------------------------------

def validate_config() -> None:
    """
    Check all required environment variables are set.

    Called once in main.py at startup.
    Logs warnings for missing values — doesn't raise, so the app can still
    start in degraded mode (useful for debugging deploy issues).
    """
    required = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY,
        "SUPABASE_ANON_KEY": SUPABASE_ANON_KEY,
    }

    # LLM key depends on which provider is active
    if ACTIVE_LLM == "gemini":
        required["GEMINI_API_KEY"] = GEMINI_API_KEY
    elif ACTIVE_LLM == "claude":
        required["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

    missing = [key for key, value in required.items() if not value]

    if missing:
        logger.warning(
            f"[Config] Missing required environment variables: {', '.join(missing)}. "
            f"Pipeline will fail until these are set."
        )
    else:
        logger.info(
            f"[Config] All required env vars present. "
            f"Active LLM: {ACTIVE_LLM} | Scheduler: every {SCHEDULER_INTERVAL_MINUTES} min"
        )
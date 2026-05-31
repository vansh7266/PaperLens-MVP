# radar/core/llm.py
#
# LLM abstraction for Research Radar summarization.
#
# Provider chain (auto-selected, no code change needed):
#   1. Cerebras    — primary (free, ~30 RPM, fast llama3.1-8b)
#   2. OpenRouter  — fallback (free models, ~20 RPM)
#   3. Groq        — last resort free fallback (6K TPM, slow)
#   4. OpenAI      — production paid option
#   5. Local stub  — dev when no keys set

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

from config import (
    CEREBRAS_API_KEY,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    RADAR_CEREBRAS_MODEL,
    RADAR_GROQ_MODEL,
    RADAR_LLM,
    RADAR_MAX_TOKENS,
    RADAR_OPENAI_MODEL,
    RADAR_OPENROUTER_MODEL,
)

logger = logging.getLogger("paperlens.radar.core.llm")

_llm_client: Optional["BaseRadarLLM"] = None


class BaseRadarLLM(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        pass


# ---------------------------------------------------------------------------
# Cerebras — primary (free, fast)
# ---------------------------------------------------------------------------

class CerebrasRadarLLM(BaseRadarLLM):
    """
    Cerebras Cloud — primary Radar summarizer.
    Free tier: ~30 RPM. OpenAI-compatible API.
    Model: llama3.1-8b (fast, good for short summaries).
    """

    def __init__(self):
        from openai import AsyncOpenAI
        if not CEREBRAS_API_KEY:
            raise RuntimeError("[Radar LLM] CEREBRAS_API_KEY not set.")
        self.client = AsyncOpenAI(
            api_key=CEREBRAS_API_KEY,
            base_url="https://api.cerebras.ai/v1",
        )
        logger.info(f"[Radar LLM] Cerebras initialized. Model: {RADAR_CEREBRAS_MODEL}")

    async def generate(self, prompt: str) -> str:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self.client.chat.completions.create(
                    model=RADAR_CEREBRAS_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=RADAR_MAX_TOKENS,
                    temperature=0.2,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    logger.warning("[Radar LLM] Cerebras returned empty.")
                    return ""
                logger.debug(f"[Radar LLM] Cerebras: {len(text)} chars.")
                return text

            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    wait = (attempt + 1) * 4  # 4s, 8s, 12s
                    logger.warning(f"[Radar LLM] Cerebras rate limit — retry in {wait}s ({attempt+1}/{max_retries})")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"[Radar LLM] Cerebras failed: {type(e).__name__}: {e}")
                return ""
        return ""


# ---------------------------------------------------------------------------
# OpenRouter — fallback (free models)
# ---------------------------------------------------------------------------

class OpenRouterRadarLLM(BaseRadarLLM):
    """
    OpenRouter — fallback Radar summarizer.
    Free models (suffix :free), ~20 RPM. OpenAI-compatible API.
    Includes required X-Title header for better rate limit allowances.
    """

    def __init__(self):
        from openai import AsyncOpenAI
        if not OPENROUTER_API_KEY:
            raise RuntimeError("[Radar LLM] OPENROUTER_API_KEY not set.")
        self.client = AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://paperlens.dev",
                "X-Title": "PaperLens Research Radar",
            },
        )
        logger.info(f"[Radar LLM] OpenRouter initialized. Model: {RADAR_OPENROUTER_MODEL}")

    async def generate(self, prompt: str) -> str:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self.client.chat.completions.create(
                    model=RADAR_OPENROUTER_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=RADAR_MAX_TOKENS,
                    temperature=0.2,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    logger.warning("[Radar LLM] OpenRouter returned empty.")
                    return ""
                logger.debug(f"[Radar LLM] OpenRouter: {len(text)} chars.")
                return text

            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    wait = (attempt + 1) * 5  # 5s, 10s, 15s
                    logger.warning(f"[Radar LLM] OpenRouter rate limit — retry in {wait}s ({attempt+1}/{max_retries})")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"[Radar LLM] OpenRouter failed: {type(e).__name__}: {e}")
                return ""
        return ""


# ---------------------------------------------------------------------------
# Groq — last resort free fallback
# ---------------------------------------------------------------------------

class GroqRadarLLM(BaseRadarLLM):
    def __init__(self):
        from groq import AsyncGroq
        if not GROQ_API_KEY:
            raise RuntimeError("[Radar LLM] GROQ_API_KEY not set.")
        self.client = AsyncGroq(api_key=GROQ_API_KEY)
        logger.info(f"[Radar LLM] Groq initialized. Model: {RADAR_GROQ_MODEL}")

    async def generate(self, prompt: str) -> str:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self.client.chat.completions.create(
                    model=RADAR_GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=RADAR_MAX_TOKENS,
                    temperature=0.2,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    return ""
                await asyncio.sleep(1.5)  # stay under 6K TPM
                return text
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    wait = (attempt + 1) * 5
                    logger.warning(f"[Radar LLM] Groq rate limit — retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"[Radar LLM] Groq failed: {type(e).__name__}: {e}")
                return ""
        return ""


# ---------------------------------------------------------------------------
# OpenAI — production paid option
# ---------------------------------------------------------------------------

class OpenAIRadarLLM(BaseRadarLLM):
    def __init__(self):
        from openai import AsyncOpenAI
        if not OPENAI_API_KEY:
            raise RuntimeError("[Radar LLM] OPENAI_API_KEY not set.")
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info(f"[Radar LLM] OpenAI initialized. Model: {RADAR_OPENAI_MODEL}")

    async def generate(self, prompt: str) -> str:
        try:
            resp = await self.client.chat.completions.create(
                model=RADAR_OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=RADAR_MAX_TOKENS,
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"[Radar LLM] OpenAI failed: {type(e).__name__}: {e}")
            return ""


# ---------------------------------------------------------------------------
# Local stub — no keys configured
# ---------------------------------------------------------------------------

class LocalRadarLLM(BaseRadarLLM):
    def __init__(self):
        logger.warning("[Radar LLM] No API key found — using local stub. Set CEREBRAS_API_KEY.")

    async def generate(self, prompt: str) -> str:
        return ""


# ---------------------------------------------------------------------------
# Factory — auto-selects provider chain
# ---------------------------------------------------------------------------

def get_radar_llm() -> BaseRadarLLM:
    """
    Returns the active Radar LLM singleton.

    Auto-selection chain (tries each in order until one initializes):
      Cerebras → OpenRouter → Groq → OpenAI → local stub

    RADAR_LLM env var sets the preferred provider but the chain
    ensures automatic fallback if a key is missing.
    """
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    # Try each provider in priority order
    providers = [
        ("cerebras",   CerebrasRadarLLM,   CEREBRAS_API_KEY),
        ("openrouter", OpenRouterRadarLLM,  OPENROUTER_API_KEY),
        ("groq",       GroqRadarLLM,        GROQ_API_KEY),
        ("openai",     OpenAIRadarLLM,      OPENAI_API_KEY),
    ]

    for name, cls, key in providers:
        if not key:
            continue
        try:
            _llm_client = cls()
            return _llm_client
        except Exception as e:
            logger.warning(f"[Radar LLM] {name} init failed: {e} — trying next provider.")

    _llm_client = LocalRadarLLM()
    return _llm_client

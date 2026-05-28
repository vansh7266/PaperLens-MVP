# core/llm.py

import logging
from abc import ABC, abstractmethod
from typing import Optional

import config

logger = logging.getLogger("paperlens.core.llm")

# Singleton — one LLM client for entire app lifetime
_llm_client: Optional["BaseLLMClient"] = None


# ---------------------------------------------------------------------------
# Abstract base — both providers implement this interface
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """
    Abstract base for all LLM provider clients.

    Every provider (Gemini, Claude) must implement generate().
    The rest of the pipeline calls only generate() — never provider-specific code.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """
        Generate a text response for the given prompt.

        Args:
            prompt: Full prompt string (built by summarizer.py)

        Returns:
            Generated text string, or "" on any failure.
            Never raises — always returns a string.
        """
        pass


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

class GeminiClient(BaseLLMClient):
    """
    LLM client for Google Gemini 2.0 Flash.

    Used during testing — cheaper per token than Claude.
    Uses google-generativeai SDK (pip install google-generativeai).
    """

    def __init__(self):
        """
        Configure Gemini SDK with API key and model settings.

        generation_config controls output length and randomness.
        safety_settings are set permissive — we're summarizing research,
        not generating user-facing content, so default filters can block
        legitimate AI safety / adversarial ML paper summaries.
        """
        try:
            import google.generativeai as genai

            if not config.GEMINI_API_KEY:
                raise RuntimeError(
                    "[LLM] GEMINI_API_KEY not set. Add it to your .env file."
                )

            # Configure SDK globally — applies to all GenerativeModel instances
            genai.configure(api_key=config.GEMINI_API_KEY)

            # generation_config: controls output shape
            generation_config = genai.GenerationConfig(
                max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,  # 150 tokens = ~2-3 sentences
                temperature=0.3,   # Low = more factual, less creative (good for summarization)
                top_p=0.8,         # Nucleus sampling — keeps output focused
            )

            # Initialize the model once — reused for all generate() calls
            self.model = genai.GenerativeModel(
                model_name=config.GEMINI_MODEL,
                generation_config=generation_config,
            )

            logger.info(f"[LLM] Gemini client initialized. Model: {config.GEMINI_MODEL}")

        except ImportError:
            raise RuntimeError(
                "[LLM] google-generativeai not installed. Run: pip install google-generativeai"
            )

    async def generate(self, prompt: str) -> str:
        """
        Generate a summary using Gemini 2.0 Flash.

        Uses generate_content_async() — non-blocking, safe for FastAPI event loop.

        Args:
            prompt: Full summarization prompt from summarizer.py

        Returns:
            Generated summary string, or "" on any failure.
        """
        try:
            # Async call — doesn't block event loop
            response = await self.model.generate_content_async(prompt)

            # Extract text from response
            # response.text raises ValueError if content was blocked by safety filters
            summary = response.text.strip()

            if not summary:
                logger.warning("[LLM] Gemini returned empty response.")
                return ""

            logger.debug(f"[LLM] Gemini generated {len(summary)} chars.")
            return summary

        except ValueError as e:
            # Triggered when Gemini's safety filters block the response
            # Common with papers on adversarial attacks, jailbreaking research etc.
            logger.warning(f"[LLM] Gemini safety filter blocked response: {e}")
            return ""

        except Exception as e:
            logger.error(
                f"[LLM] Gemini generate() failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return ""


# ---------------------------------------------------------------------------
# Claude provider
# ---------------------------------------------------------------------------

class ClaudeClient(BaseLLMClient):
    """
    LLM client for Anthropic Claude Haiku.

    Used in production — higher quality summaries than Gemini Flash.
    Uses anthropic SDK (pip install anthropic).
    """

    def __init__(self):
        """
        Initialize async Anthropic client with API key.

        AsyncAnthropic is the async version of the client —
        required for non-blocking use in FastAPI.
        """
        try:
            from anthropic import AsyncAnthropic

            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError(
                    "[LLM] ANTHROPIC_API_KEY not set. Add it to your .env file."
                )

            # AsyncAnthropic handles connection pooling internally
            self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

            logger.info(f"[LLM] Claude client initialized. Model: {config.CLAUDE_MODEL}")

        except ImportError:
            raise RuntimeError(
                "[LLM] anthropic not installed. Run: pip install anthropic"
            )

    async def generate(self, prompt: str) -> str:
        """
        Generate a summary using Claude Haiku.

        Uses messages.create() with async client — non-blocking.

        Args:
            prompt: Full summarization prompt from summarizer.py

        Returns:
            Generated summary string, or "" on any failure.
        """
        try:
            response = await self.client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            # response.content is a list of content blocks
            # For text generation, first block is always TextBlock with .text attribute
            if not response.content:
                logger.warning("[LLM] Claude returned empty content list.")
                return ""

            summary = response.content[0].text.strip()

            if not summary:
                logger.warning("[LLM] Claude returned empty text block.")
                return ""

            logger.debug(f"[LLM] Claude generated {len(summary)} chars.")
            return summary

        except Exception as e:
            logger.error(
                f"[LLM] Claude generate() failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return ""


# ---------------------------------------------------------------------------
# Factory — returns correct client based on config
# ---------------------------------------------------------------------------

def get_llm_client() -> BaseLLMClient:
    """
    Return the active LLM client singleton based on config.ACTIVE_LLM.

    Reads ACTIVE_LLM from config.py:
      "gemini" → GeminiClient (testing)
      "claude" → ClaudeClient (production)

    Singleton: initialized once, reused for entire app lifetime.
    Switching providers requires only changing ACTIVE_LLM in .env — no code changes.

    Returns:
        Initialized BaseLLMClient subclass (GeminiClient or ClaudeClient)

    Raises:
        RuntimeError: If ACTIVE_LLM is an unknown value or API key is missing.
                      Fail fast at startup — better than silent wrong behavior.
    """
    global _llm_client

    # Return cached instance if already initialized
    if _llm_client is not None:
        return _llm_client

    active = config.ACTIVE_LLM.lower().strip()

    if active == "gemini":
        _llm_client = GeminiClient()

    elif active == "claude":
        _llm_client = ClaudeClient()

    else:
        raise RuntimeError(
            f"[LLM] Unknown ACTIVE_LLM value: '{config.ACTIVE_LLM}'. "
            f"Must be 'gemini' or 'claude'."
        )

    return _llm_client
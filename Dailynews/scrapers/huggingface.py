# scrapers/huggingface.py

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from scrapers.base import BaseScraper

logger = logging.getLogger("paperlens.scrapers.huggingface")

# ---------------------------------------------------------------------------
# HuggingFace Hub API endpoint for model listings
# Query params:
#   sort=lastModified  — newest models first
#   direction=-1       — descending order
#   limit=50           — max items per request (HF allows up to 100)
#   full=False         — don't return full model card (keeps response small)
# ---------------------------------------------------------------------------
HF_API_URL = (
    "https://huggingface.co/api/models"
    "?sort=lastModified&direction=-1&limit=50&full=false"
)

# HuggingFace model page base URL — used to build source_url from model ID
HF_MODEL_BASE_URL = "https://huggingface.co/"


class HuggingFaceScraper(BaseScraper):
    """
    Scraper for new model releases from the HuggingFace Hub API.

    Uses the official HF REST API (JSON) instead of RSS.
    Returns models sorted by last modified date — newest first.

    API key is optional but recommended:
      - Without key: 30 req/min rate limit
      - With key:    higher limits + access to gated models

    Inherits fetch_url(), retry logic, and connection pooling from BaseScraper.
    """

    def __init__(self):
        """
        Initialize scraper and load optional HF API key from environment.

        The API key is passed as a Bearer token in the Authorization header.
        fetch_url() accepts headers — we build them here once and reuse.
        """
        super().__init__(source_name="HuggingFace")

        # Load API key from environment — never hardcode
        api_key = os.getenv("HUGGINGFACE_API_KEY")

        # Build headers dict — used in every fetch_url() call
        # If no key, we still send a valid (unauthenticated) request
        if api_key:
            self.headers = {"Authorization": f"Bearer {api_key}"}
            logger.info("[HuggingFace] API key loaded — authenticated requests.")
        else:
            self.headers = {}
            logger.warning(
                "[HuggingFace] No HUGGINGFACE_API_KEY found. "
                "Using unauthenticated requests (rate limit: 30 req/min)."
            )

    # -----------------------------------------------------------------------
    # URL builder
    # -----------------------------------------------------------------------

    def _build_model_url(self, model_id: str) -> str:
        """
        Build the canonical HuggingFace model page URL from a model ID.

        HF model IDs follow the pattern: "owner/model-name"
        e.g. "meta-llama/Llama-3-8B" → "https://huggingface.co/meta-llama/Llama-3-8B"

        Args:
            model_id: HF model ID string (e.g. "mistralai/Mistral-7B-v0.1")

        Returns:
            Full HTTPS URL to the model page
        """
        # model_id already contains owner/name — just append to base URL
        return f"{HF_MODEL_BASE_URL}{model_id}"

    # -----------------------------------------------------------------------
    # Date normalization
    # -----------------------------------------------------------------------

    def _parse_hf_date(self, raw_date: Optional[str]) -> Optional[str]:
        """
        Parse HuggingFace API date string to ISO 8601 format.

        HF API returns dates as ISO 8601 strings already (e.g. "2024-01-15T10:30:00.000Z")
        but we normalize to ensure consistency (strip milliseconds, force UTC format).

        Args:
            raw_date: Date string from HF API, or None

        Returns:
            ISO 8601 datetime string (e.g. "2024-01-15T10:30:00"), or None
        """
        if not raw_date:
            return None

        try:
            # HF dates look like: "2024-01-15T10:30:00.000Z"
            # Strip trailing Z and milliseconds, then parse
            clean = raw_date.replace("Z", "+00:00")  # Make timezone-aware
            dt = datetime.datetime.fromisoformat(clean)
            # Return without microseconds — clean ISO format for PostgreSQL
            return dt.strftime("%Y-%m-%dT%H:%M:%S")

        except (ValueError, AttributeError) as e:
            logger.warning(f"[HuggingFace] Could not parse date '{raw_date}': {e}")
            return None

    # -----------------------------------------------------------------------
    # JSON parsing
    # -----------------------------------------------------------------------

    def _parse_response(self, raw_json: str) -> list[dict]:
        """
        Parse the raw JSON response from HF API into a list of model dicts.

        HF API returns a JSON array of model objects. Each object contains:
          - modelId: "owner/model-name"
          - lastModified: ISO date string
          - tags: list of strings (e.g. ["text-generation", "pytorch"])
          - likes: integer
          - downloads: integer
          - pipeline_tag: primary task (e.g. "text-generation")
          - cardData: dict with model card metadata (may be absent)

        Args:
            raw_json: Raw JSON string from fetch_url()

        Returns:
            Parsed list of model dicts, or [] on parse failure
        """
        try:
            data = json.loads(raw_json)

            # HF API should return a list — validate
            if not isinstance(data, list):
                logger.error(
                    f"[HuggingFace] Unexpected API response format: expected list, "
                    f"got {type(data).__name__}"
                )
                return []

            return data

        except json.JSONDecodeError as e:
            logger.error(f"[HuggingFace] Failed to parse JSON response: {e}", exc_info=True)
            return []

    # -----------------------------------------------------------------------
    # Main scrape()
    # -----------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Fetch and return the latest model releases from HuggingFace Hub API.

        Steps:
          1. fetch_url() with auth headers → raw JSON string
          2. Parse JSON → list of model objects
          3. Convert each model object → content_items schema dict

        Returns:
            List of content item dicts ready for pipeline/processor.py.
            Returns [] on any failure — never raises.
        """
        logger.info("[HuggingFace] Starting model scrape.")

        # Step 1: Fetch raw JSON from HF API
        # Pass self.headers — includes Bearer token if API key is set
        raw_json = await self.fetch_url(HF_API_URL, headers=self.headers)

        if raw_json is None:
            # fetch_url already logged the error
            logger.warning("[HuggingFace] Fetch returned None — skipping this cycle.")
            return []

        # Step 2: Parse JSON response into list of model objects
        models = self._parse_response(raw_json)

        if not models:
            logger.info("[HuggingFace] No models returned from API.")
            return []

        # Step 3: Convert each model object to our content_items schema
        items = []
        for model in models:
            try:
                # --- Extract model ID (required field) ---
                model_id = model.get("modelId", "").strip()

                if not model_id:
                    logger.debug("[HuggingFace] Skipping model with missing modelId.")
                    continue

                # --- Build canonical source URL ---
                source_url = self._build_model_url(model_id)

                # --- Extract title ---
                # Use model_id as title — it's the standard way HF models are referenced
                # e.g. "meta-llama/Llama-3-8B" is more useful than any description
                title = model_id

                # --- Extract authors ---
                # HF model ID format is "owner/model-name" — owner is the author/org
                # Return as list to match TEXT[] schema (same as arXiv fix)
                owner = model_id.split("/")[0] if "/" in model_id else model_id
                authors = [owner]

                # --- Extract dates ---
                published_at = self._parse_hf_date(model.get("lastModified"))

                # --- Extract tags ---
                tags = model.get("tags", [])  # List of strings e.g. ["llm", "pytorch"]
                pipeline_tag = model.get("pipeline_tag", "")  # Primary task

                # --- Extract popularity signals for attention_score ---
                likes = model.get("likes", 0)
                downloads = model.get("downloads", 0)

                # --- Build description from pipeline_tag + tags ---
                # HF models often have no description in the API response
                # pipeline_tag tells us the primary use case (e.g. "text-generation")
                description_parts = []
                if pipeline_tag:
                    description_parts.append(f"Task: {pipeline_tag}")
                if tags:
                    # Show first 5 tags — enough context without being verbose
                    description_parts.append(f"Tags: {', '.join(tags[:5])}")
                full_content = " | ".join(description_parts) if description_parts else ""

                # --- Build content item dict matching content_items schema ---
                item = {
                    "title": title,
                    "source_url": source_url,       # UNIQUE — used for deduplication in DB
                    "source_name": "HuggingFace",
                    "content_type": "model",        # Always "model" for HF releases
                    "arxiv_id": None,               # HF models have no arXiv ID
                    "authors": authors,             # List — matches TEXT[] schema
                    "full_content": full_content,   # Task + tags as description
                    "published_at": published_at,   # ISO 8601 string
                    "metadata_json": {
                        "model_id": model_id,       # Full "owner/name" for HF API calls later
                        "pipeline_tag": pipeline_tag,
                        "tags": tags,
                        "likes": likes,
                        "downloads": downloads,
                    },
                    # Fields set by processor — not scrapers
                    "topic": None,
                    "difficulty": None,
                    "attention_score": None,
                    "is_summarized": False,
                    "is_released": False,
                }

                items.append(item)

            except Exception as e:
                # Never let one bad model crash the entire scrape
                logger.error(
                    f"[HuggingFace] Error processing model '{model.get('modelId', 'unknown')}': "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue

        logger.info(f"[HuggingFace] Scrape complete. {len(items)} models scraped.")
        return items
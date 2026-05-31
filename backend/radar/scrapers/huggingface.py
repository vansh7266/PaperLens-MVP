# radar/scrapers/huggingface.py
#
# HuggingFace Hub API scraper — fetches recent AI-relevant model releases.
# Applies quality filters to skip low-signal / irrelevant models.

import datetime
import json
import logging
import os
from typing import Optional

from radar.scrapers.base import BaseScraper
from config import HF_MIN_LIKES, HF_MIN_DOWNLOADS, HF_RELEVANT_PIPELINE_TAGS

logger = logging.getLogger("paperlens.radar.scrapers.huggingface")

# HF API endpoint — newest models first, limit 100 per request
HF_API_URL = (
    "https://huggingface.co/api/models"
    "?sort=lastModified&direction=-1&limit=100&full=false"
)
HF_MODEL_BASE_URL = "https://huggingface.co/"


class HuggingFaceScraper(BaseScraper):
    """
    Fetches recent model releases from HuggingFace Hub API.

    Quality filters applied (configurable via config.py):
      - pipeline_tag must be in HF_RELEVANT_PIPELINE_TAGS (AI-relevant tasks only)
      - likes >= HF_MIN_LIKES OR downloads >= HF_MIN_DOWNLOADS
        → prevents random personal fine-tunes from flooding the feed

    API key is optional but recommended for higher rate limits.
    """

    def __init__(self):
        super().__init__(source_name="HuggingFace")

        api_key = os.getenv("HUGGINGFACE_API_KEY")
        if api_key:
            self.headers = {"Authorization": f"Bearer {api_key}"}
            logger.info("[HuggingFace] API key loaded — authenticated requests.")
        else:
            self.headers = {}
            logger.warning(
                "[HuggingFace] No HUGGINGFACE_API_KEY. "
                "Using unauthenticated requests (rate limit: 30 req/min)."
            )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_model_url(self, model_id: str) -> str:
        return f"{HF_MODEL_BASE_URL}{model_id}"

    def _parse_hf_date(self, raw_date: Optional[str]) -> Optional[str]:
        """Parse HF ISO date string → clean ISO without milliseconds."""
        if not raw_date:
            return None
        try:
            clean = raw_date.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(clean)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, AttributeError) as e:
            logger.warning(f"[HuggingFace] Could not parse date '{raw_date}': {e}")
            return None

    def _is_relevant(self, model: dict) -> bool:
        """
        Quality gate: skip low-signal or irrelevant models.

        Rules:
          1. pipeline_tag must be in HF_RELEVANT_PIPELINE_TAGS
             (skips models with no task tag or irrelevant tasks)
          2. likes >= HF_MIN_LIKES OR downloads >= HF_MIN_DOWNLOADS
             (skips brand-new models with zero traction — likely personal fine-tunes)

        Returns True if model should be included.
        """
        pipeline_tag = (model.get("pipeline_tag") or "").strip().lower()
        if not pipeline_tag:
            return False  # No task category — skip

        # Normalize for comparison (HF uses both formats)
        relevant_tags_lower = [t.lower() for t in HF_RELEVANT_PIPELINE_TAGS]
        if pipeline_tag not in relevant_tags_lower:
            return False

        likes     = model.get("likes", 0) or 0
        downloads = model.get("downloads", 0) or 0

        return likes >= HF_MIN_LIKES or downloads >= HF_MIN_DOWNLOADS

    def _parse_response(self, raw_json: str) -> list[dict]:
        """Parse HF API JSON array response."""
        try:
            data = json.loads(raw_json)
            if not isinstance(data, list):
                logger.error(
                    f"[HuggingFace] Unexpected API format: expected list, got {type(data).__name__}"
                )
                return []
            return data
        except json.JSONDecodeError as e:
            logger.error(f"[HuggingFace] JSON parse error: {e}", exc_info=True)
            return []

    # -------------------------------------------------------------------------
    # Main scrape()
    # -------------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Fetch latest HuggingFace model releases.
        Applies quality filter before returning.
        Returns [] on any failure.
        """
        logger.info("[HuggingFace] Starting model scrape.")

        raw_json = await self.fetch_url(HF_API_URL, headers=self.headers)
        if raw_json is None:
            return []

        models = self._parse_response(raw_json)
        if not models:
            return []

        items = []
        skipped = 0

        for model in models:
            try:
                model_id = model.get("modelId", "").strip()
                if not model_id:
                    continue

                # --- Quality gate ---
                if not self._is_relevant(model):
                    skipped += 1
                    continue

                source_url   = self._build_model_url(model_id)
                published_at = self._parse_hf_date(model.get("lastModified"))

                pipeline_tag = model.get("pipeline_tag", "")
                tags         = model.get("tags", [])
                likes        = model.get("likes", 0) or 0
                downloads    = model.get("downloads", 0) or 0

                # Owner of model ID = first segment before "/"
                owner   = model_id.split("/")[0] if "/" in model_id else model_id
                authors = [owner]

                # Build a human-readable description from pipeline_tag + tags
                desc_parts = []
                if pipeline_tag:
                    desc_parts.append(f"Task: {pipeline_tag}")
                if tags:
                    desc_parts.append(f"Tags: {', '.join(tags[:6])}")
                full_content = " | ".join(desc_parts)

                items.append({
                    "title":        model_id,
                    "source_url":   source_url,
                    "source_name":  "HuggingFace",
                    "content_type": "model",
                    "arxiv_id":     None,
                    "authors":      authors,
                    "full_content": full_content,
                    "published_at": published_at,
                    "metadata_json": {
                        "model_id":     model_id,
                        "pipeline_tag": pipeline_tag,
                        "tags":         tags,
                        "likes":        likes,
                        "downloads":    downloads,
                    },
                    "topic":           None,
                    "difficulty":      None,
                    "attention_score": None,
                    "is_summarized":   False,
                    "is_released":     False,
                })

            except Exception as e:
                logger.error(
                    f"[HuggingFace] Error processing model '{model.get('modelId', 'unknown')}': "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                continue

        logger.info(
            f"[HuggingFace] Done. {len(items)} kept, {skipped} skipped by quality filter."
        )
        return items

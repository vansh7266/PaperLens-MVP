# radar/pipeline/summarizer.py
#
# Generates summaries for content items using LLM.
# KEY PRINCIPLE: Summarize ONCE per item, serve to all users forever.
# 10,000 users reading the same paper = 1 LLM call total.
#
# Per item, generates TWO fields in ONE LLM call:
#   summary        — 2-3 sentence plain English summary
#   why_it_matters — 1-2 sentence "so what" for researchers
#
# This is intentional: one call per item instead of two.

import asyncio
import logging
from typing import Optional

from radar.core.llm import get_radar_llm
from radar.core.database import get_service_client
from config import RADAR_MAX_CONCURRENT_SUMMARIES, RADAR_MAX_CONTENT_CHARS

logger = logging.getLogger("paperlens.radar.pipeline.summarizer")

# ---------------------------------------------------------------------------
# Prompt template — structured JSON output so we can parse both fields
# ---------------------------------------------------------------------------
SUMMARY_PROMPT_TEMPLATE = """\
You are a research analyst for AI/ML professionals.

Given the content below, write two things:

1. SUMMARY: 2-3 sentences of plain English.
   - Focus on: what it is, what problem it solves, what method/approach
   - Do NOT start with "This paper" or "This post"
   - No jargon unless essential

2. WHY_IT_MATTERS: 1-2 sentences explaining practical significance.
   - Why should an AI/ML researcher or engineer care?
   - What does this enable or change?
   - Be direct and concrete

Respond in this exact format (nothing else):
SUMMARY: <your summary here>
WHY_IT_MATTERS: <your why it matters here>

---
Type: {content_type}
Title: {title}
Content: {content}
"""


class Summarizer:
    """
    Generates summary + why_it_matters for content items.

    Works on items with is_summarized=False.
    After success, immediately updates the DB row:
      - summary = generated text
      - why_it_matters = generated text
      - is_summarized = True

    If the DB update succeeds before the scheduler crashes,
    the item won't be re-processed on the next cycle.
    Concurrency controlled via asyncio.Semaphore.
    """

    def __init__(self):
        self.llm       = get_radar_llm()
        self.semaphore = asyncio.Semaphore(RADAR_MAX_CONCURRENT_SUMMARIES)
        logger.info("[Summarizer] Initialized.")

    # -----------------------------------------------------------------------
    # Prompt builder
    # -----------------------------------------------------------------------

    def _build_prompt(self, title: str, full_content: str, content_type: str) -> str:
        truncated = full_content[:RADAR_MAX_CONTENT_CHARS]
        if len(full_content) > RADAR_MAX_CONTENT_CHARS:
            truncated += "\n[Content truncated]"
        return SUMMARY_PROMPT_TEMPLATE.format(
            content_type=content_type or "unknown",
            title=title,
            content=truncated or "No content available.",
        )

    # -----------------------------------------------------------------------
    # Parse LLM response
    # -----------------------------------------------------------------------

    def _parse_response(self, text: str) -> tuple[str, str]:
        """
        Parse the structured LLM response into (summary, why_it_matters).
        Falls back gracefully if the LLM doesn't follow the format exactly.

        Expected format:
          SUMMARY: <text>
          WHY_IT_MATTERS: <text>
        """
        summary        = ""
        why_it_matters = ""

        lines = text.strip().splitlines()
        current_field = None
        buf: list[str] = []

        for line in lines:
            if line.startswith("SUMMARY:"):
                if current_field == "WHY":
                    why_it_matters = " ".join(buf).strip()
                    buf = []
                current_field = "SUM"
                buf.append(line[len("SUMMARY:"):].strip())

            elif line.startswith("WHY_IT_MATTERS:"):
                if current_field == "SUM":
                    summary = " ".join(buf).strip()
                    buf = []
                current_field = "WHY"
                buf.append(line[len("WHY_IT_MATTERS:"):].strip())

            else:
                if line.strip():
                    buf.append(line.strip())

        # Flush last field
        if current_field == "SUM" and not summary:
            summary = " ".join(buf).strip()
        elif current_field == "WHY" and not why_it_matters:
            why_it_matters = " ".join(buf).strip()

        # Fallback: if format wasn't followed, use full text as summary
        if not summary and text.strip():
            summary = text.strip()[:500]

        return summary, why_it_matters

    # -----------------------------------------------------------------------
    # Summarize one item
    # -----------------------------------------------------------------------

    async def _summarize_one(
        self, item_id: str, title: str, full_content: str, content_type: str
    ) -> Optional[tuple[str, str]]:
        """
        Generate (summary, why_it_matters) for a single item.
        Returns None on any failure — item stays is_summarized=False,
        retried on next scheduler cycle.
        """
        async with self.semaphore:
            try:
                prompt = self._build_prompt(title, full_content, content_type)
                logger.debug(f"[Summarizer] Generating for: {item_id}")

                raw = await self.llm.generate(prompt)
                if not raw:
                    logger.warning(f"[Summarizer] LLM returned empty for {item_id}.")
                    return None

                summary, why = self._parse_response(raw)

                if not summary:
                    logger.warning(f"[Summarizer] Could not parse summary for {item_id}.")
                    return None

                return summary, why

            except Exception as e:
                logger.error(
                    f"[Summarizer] LLM error for {item_id}: {type(e).__name__}: {e}",
                    exc_info=True,
                )
                return None

    # -----------------------------------------------------------------------
    # Save to DB
    # -----------------------------------------------------------------------

    async def _save_summary(
        self, item_id: str, summary: str, why_it_matters: str
    ) -> bool:
        """Save summary + why_it_matters to DB, mark is_summarized=True."""
        try:
            db = await get_service_client()
            resp = await (
                db.table("content_items")
                .update({
                    "summary":        summary,
                    "why_it_matters": why_it_matters,
                    "is_summarized":  True,
                })
                .eq("id", item_id)
                .execute()
            )
            if resp.data:
                logger.debug(f"[Summarizer] Saved summary for {item_id}.")
                return True
            logger.warning(f"[Summarizer] No data returned for update on {item_id}.")
            return False
        except Exception as e:
            logger.error(f"[Summarizer] DB error saving summary: {e}", exc_info=True)
            return False

    # -----------------------------------------------------------------------
    # Orchestrate one item
    # -----------------------------------------------------------------------

    async def _process_one(self, item: dict) -> dict:
        """Summarize + save one item. Returns item with updated fields."""
        item_id      = item.get("id")
        title        = item.get("title", "")
        full_content = item.get("full_content", "")
        content_type = item.get("content_type", "")

        if not item_id:
            logger.warning(f"[Summarizer] Item missing 'id': {title[:50]}")
            return item

        result = await self._summarize_one(item_id, title, full_content, content_type)

        if result:
            summary, why = result
            saved = await self._save_summary(item_id, summary, why)
            if saved:
                item["summary"]        = summary
                item["why_it_matters"] = why
                item["is_summarized"]  = True
        else:
            logger.warning(f"[Summarizer] Skipping DB update for {item_id} — no summary.")

        return item

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    async def summarize_batch(self, items: list[dict]) -> list[dict]:
        """
        Summarize a batch in parallel (concurrency controlled by semaphore).

        Only processes items where is_summarized=False.
        Items with is_summarized=True are passed through unchanged.

        Args:
            items: List of content item dicts with 'id' field (from DB after insert)

        Returns:
            Same list with summary/why_it_matters/is_summarized updated where successful.
        """
        if not items:
            return []

        to_summarize = [i for i in items if not i.get("is_summarized", False)]
        already_done = [i for i in items if i.get("is_summarized", False)]

        logger.info(
            f"[Summarizer] Batch: {len(items)} total | "
            f"{len(to_summarize)} to summarize | {len(already_done)} already done."
        )

        if not to_summarize:
            return items

        results = await asyncio.gather(
            *[self._process_one(item) for item in to_summarize],
            return_exceptions=True,
        )

        final: list[dict] = []
        for item, result in zip(to_summarize, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[Summarizer] Unhandled exception for {item.get('id', 'unknown')}: "
                    f"{type(result).__name__}: {result}"
                )
                final.append(item)  # return unchanged, retry next cycle
            else:
                final.append(result)

        success_count = sum(1 for i in final if i.get("is_summarized"))
        logger.info(
            f"[Summarizer] Done. {success_count}/{len(to_summarize)} summaries generated."
        )

        return final + already_done

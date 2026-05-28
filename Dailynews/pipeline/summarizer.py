# pipeline/summarizer.py

import asyncio
import logging
from typing import Optional

from core.llm import get_llm_client
from core.database import get_service_client

logger = logging.getLogger("paperlens.pipeline.summarizer")

# ---------------------------------------------------------------------------
# Concurrency limit — max simultaneous LLM API calls
# Prevents hammering Gemini/Claude API with 50 requests at once
# asyncio.Semaphore(5) = max 5 summaries generated in parallel
# ---------------------------------------------------------------------------
MAX_CONCURRENT_SUMMARIES = 5

# ---------------------------------------------------------------------------
# Prompt template — used for ALL content types (papers, models, blog posts)
# Designed to produce 2-3 sentences of plain English regardless of input
# ---------------------------------------------------------------------------
SUMMARY_PROMPT_TEMPLATE = """You are a research assistant for AI/ML professionals.

Summarize the following content in exactly 2-3 sentences of plain English.
- No jargon unless essential
- Focus on: what it is, what problem it solves, why it matters
- Do NOT start with "This paper" or "This post"
- Do NOT include citations or references

Title: {title}

Content:
{content}

Summary:"""

# Max characters of full_content sent to LLM
# Keeps token cost low — abstracts are rarely longer than this
MAX_CONTENT_CHARS = 2000


class Summarizer:
    """
    Generates and stores plain English summaries for content items.

    Works on items returned by processor.py that have is_summarized=False.
    After generating a summary, immediately updates the DB row:
      - summary = generated text
      - is_summarized = True

    This ensures that if the scheduler crashes mid-batch, already-summarized
    items are not re-processed on the next cycle.

    Uses core/llm.py for all LLM calls — switching Gemini↔Claude
    requires changing ACTIVE_LLM in config.py only.
    """

    def __init__(self):
        self.llm = get_llm_client()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUMMARIES)
        logger.info("[Summarizer] Initialized.")

    # -----------------------------------------------------------------------
    # Prompt builder
    # -----------------------------------------------------------------------

    def _build_prompt(self, title: str, full_content: str) -> str:
        """
        Build the LLM prompt for a single content item.

        Truncates full_content to MAX_CONTENT_CHARS to control token cost.
        For arXiv papers, full_content is the abstract (~1500 chars typically).
        For blog posts, it's the RSS description.
        For HF models, it's the task + tags string.

        Args:
            title:        Item title
            full_content: Abstract, description, or summary from scraper

        Returns:
            Formatted prompt string ready for LLM
        """
        # Truncate content if too long — keeps cost predictable
        truncated_content = full_content[:MAX_CONTENT_CHARS]

        # Add truncation notice if we cut the content
        if len(full_content) > MAX_CONTENT_CHARS:
            truncated_content += "\n[Content truncated for brevity]"

        return SUMMARY_PROMPT_TEMPLATE.format(
            title=title,
            content=truncated_content or "No content available.",
        )

    # -----------------------------------------------------------------------
    # Single item summarization
    # -----------------------------------------------------------------------

    async def _summarize_one(self, item_id: str, title: str, full_content: str) -> Optional[str]:
        """
        Generate a summary for a single content item using the LLM.

        Uses semaphore to limit concurrent calls — prevents API rate limit errors.
        On any failure, returns None (item stays is_summarized=False,
        will be retried on next scheduler cycle).

        Args:
            item_id:      Supabase row UUID — used for DB update after success
            title:        Item title
            full_content: Abstract or description to summarize

        Returns:
            Generated summary string, or None on failure
        """
        # Semaphore: only MAX_CONCURRENT_SUMMARIES coroutines run this block at once
        async with self.semaphore:
            try:
                prompt = self._build_prompt(title, full_content)

                logger.debug(f"[Summarizer] Generating summary for item: {item_id}")

                # Call LLM via core/llm.py abstraction
                # generate() handles Gemini/Claude switching internally
                summary = await self.llm.generate(prompt)

                if not summary or not summary.strip():
                    logger.warning(
                        f"[Summarizer] LLM returned empty summary for item {item_id}."
                    )
                    return None

                return summary.strip()

            except Exception as e:
                logger.error(
                    f"[Summarizer] LLM error for item {item_id}: "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                return None

    # -----------------------------------------------------------------------
    # DB update after successful summarization
    # -----------------------------------------------------------------------

    async def _save_summary(self, item_id: str, summary: str) -> bool:
        """
        Save generated summary to DB and mark item as summarized.
        """
        try:
            db = await get_service_client()
            response = await (
                db.table("content_items")
                .update({"summary": summary, "is_summarized": True})
                .eq("id", item_id)
                .execute()
            )
            if response.data:
                logger.debug(f"[Summarizer] Saved summary for {item_id}.")
                return True
            logger.warning(f"[Summarizer] No data returned for update on {item_id}.")
            return False
        except Exception as e:
            logger.error(f"[Summarizer] DB error saving summary: {e}", exc_info=True)
            return False

    # -----------------------------------------------------------------------
    # Per-item orchestration (summarize + save)
    # -----------------------------------------------------------------------

    async def _process_one(self, item: dict) -> dict:
        """
        Summarize a single item and save to DB if successful.

        Orchestrates _summarize_one() → _save_summary().
        Returns the item dict with summary + is_summarized fields updated
        (reflects actual outcome — success or failure).

        Args:
            item: Processed content item dict (must have 'id', 'title', 'full_content')

        Returns:
            Item dict with summary and is_summarized fields updated
        """
        item_id = item.get("id")
        title = item.get("title", "")
        full_content = item.get("full_content", "")

        # Validate required fields
        if not item_id:
            logger.warning(
                f"[Summarizer] Item missing 'id' — cannot save to DB. "
                f"Title: {title[:50]}"
            )
            return item

        # Generate summary via LLM
        summary = await self._summarize_one(item_id, title, full_content)

        if summary:
            # Save to DB — update summary + flip is_summarized flag
            saved = await self._save_summary(item_id, summary)

            if saved:
                # Update local dict to reflect DB state
                item["summary"] = summary
                item["is_summarized"] = True
        else:
            # LLM failed — item stays is_summarized=False
            # Scheduler will retry on next cycle (item already in DB from insert)
            logger.warning(
                f"[Summarizer] Skipping DB update for {item_id} — no summary generated."
            )

        return item

    # -----------------------------------------------------------------------
    # Main summarize_batch() — entry point for scheduler
    # -----------------------------------------------------------------------

    async def summarize_batch(self, items: list[dict]) -> list[dict]:
        """
        Summarize a batch of content items in parallel (with concurrency limit).

        Called by scheduler AFTER processor.py returns new items AND
        after they've been inserted into the DB (items have 'id' from DB).

        Only processes items where is_summarized=False.
        Items already summarized are passed through unchanged.

        Uses asyncio.gather() for parallelism — semaphore limits actual
        concurrent LLM calls to MAX_CONCURRENT_SUMMARIES.

        Args:
            items: List of processed content item dicts from processor.py
                   Must include 'id' (Supabase UUID) for DB updates to work

        Returns:
            Same list with summary + is_summarized updated where successful.
            Never raises — returns items as-is on unexpected errors.
        """
        if not items:
            logger.info("[Summarizer] No items to summarize.")
            return []

        # Filter: only items that haven't been summarized yet
        to_summarize = [item for item in items if not item.get("is_summarized", False)]
        already_done = [item for item in items if item.get("is_summarized", False)]

        logger.info(
            f"[Summarizer] Batch received {len(items)} items. "
            f"{len(to_summarize)} to summarize, {len(already_done)} already done."
        )

        if not to_summarize:
            logger.info("[Summarizer] All items already summarized.")
            return items

        # Run all summarizations in parallel — semaphore controls concurrency
        # return_exceptions=True — one failure doesn't cancel others
        results = await asyncio.gather(
            *[self._process_one(item) for item in to_summarize],
            return_exceptions=True,
        )

        # Handle any unexpected exceptions from gather
        final_results = []
        for item, result in zip(to_summarize, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[Summarizer] Unhandled exception for item "
                    f"'{item.get('id', 'unknown')}': "
                    f"{type(result).__name__}: {result}"
                )
                # Return original item unchanged — is_summarized stays False
                final_results.append(item)
            else:
                final_results.append(result)

        # Count successes for logging
        success_count = sum(1 for item in final_results if item.get("is_summarized"))
        logger.info(
            f"[Summarizer] Batch complete. "
            f"{success_count}/{len(to_summarize)} summaries generated successfully."
        )

        # Return all items: newly summarized + already done
        return final_results + already_done
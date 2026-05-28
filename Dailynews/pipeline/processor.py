# pipeline/processor.py

import logging
import math
import datetime
from typing import Optional

from core.database import get_service_client

logger = logging.getLogger("paperlens.pipeline.processor")

# ---------------------------------------------------------------------------
# TOPIC CLASSIFICATION — keyword rules, $0 cost
# Order matters: more specific topics checked first
# Each key is a topic name, value is a list of keywords to search for
# We search in: title + full_content (abstract/summary) — lowercased
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Multimodal": [
        "vision-language", "multimodal", "clip", "image-text",
        "visual question", "vqa", "image captioning",
    ],
    "Generative_AI": [
        "gan", "vae", "variational autoencoder", "generative adversarial",
        "stable diffusion", "image generation", "text-to-image",
    ],
    "CV": [
        "cnn", "resnet", "convolutional", "vision", "image classification",
        "object detection", "segmentation", "diffusion model",
    ],
    "RL": [
        "reinforcement learning", "policy gradient", "q-learning", "ppo",
        "proximal policy", "reward", "markov decision", "actor-critic",
    ],
    "NLP": [
        "bert", "tokenization", "embedding", "sequence-to-sequence",
        "named entity", "sentiment", "text classification", "coreference",
    ],
    "LLMs": [
        "transformer", "attention mechanism", "large language model",
        "llm", "gpt", "language model", "instruction tuning",
        "chain of thought", "in-context learning", "prompt",
    ],
    # Default fallback — assigned if no keywords match
    # "General_AI" is set explicitly at the end of classify_topic()
}

# ---------------------------------------------------------------------------
# DIFFICULTY DETECTION — keyword rules, $0 cost
# Checked in order: Advanced → Easy → default Intermediate
# We search in: title + full_content — lowercased
# ---------------------------------------------------------------------------
DIFFICULTY_KEYWORDS: dict[str, list[str]] = {
    "Advanced": [
        "theorem", "proof", "lemma", "convergence", "gradient descent",
        "backpropagation", "entropy", "kl divergence", "variational inference",
        "stochastic", "asymptotic", "regret bound",
    ],
    "Easy": [
        "survey", "overview", "introduction to", "tutorial", "beginners",
        "explained", "getting started", "what is", "guide to",
    ],
    # "Intermediate" is the default — not in this dict, assigned as fallback
}

# ---------------------------------------------------------------------------
# SOURCE WEIGHT — fixed scores per source, used in attention score formula
# Higher = more trusted/relevant for AI/ML professionals
# ---------------------------------------------------------------------------
SOURCE_WEIGHTS: dict[str, int] = {
    "arXiv": 10,
    "HuggingFace": 8,
    # All blog sources get 7 — covers Anthropic, OpenAI, DeepMind, Meta AI, Mistral
    "default": 7,
}


class Processor:
    """
    Processes raw scraper output into DB-ready content items.

    Responsibilities:
      1. Deduplication — skip items already in Supabase
      2. Topic classification — keyword rules, no AI cost
      3. Difficulty detection — keyword rules, no AI cost
      4. Attention score — recency + source weight + citation bonus
      5. Default field normalization — ensures all DB columns have values

    Does NOT write to the database — only reads for dedup checks.
    The scheduler handles batch inserts after processing.
    """

    def __init__(self):
        logger.info("[Processor] Initialized.")

    # -----------------------------------------------------------------------
    # Deduplication — DB lookup
    # -----------------------------------------------------------------------

    async def _get_existing_urls(self, source_urls: list[str]) -> set[str]:
        """
        Batch check: fetch all source_urls from DB that match our batch.
        One query instead of N queries — prevents N+1 performance issue.
        """
        try:
            db = await get_service_client()
            response = await (
                db.table("content_items")
                .select("source_url")
                .in_("source_url", source_urls)
                .execute()
            )
            return {row["source_url"] for row in response.data or []}
        except Exception as e:
            logger.error(
                f"[Processor] Batch dedup query failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            # On DB error, return empty set — items will attempt insert
            # upsert in scheduler handles actual duplicates safely
            return set()

    async def _get_existing_arxiv_ids(self, arxiv_ids: list[str]) -> set[str]:
        """
        Batch check for arXiv IDs — catches same paper from multiple RSS categories.
        Only called if batch contains arxiv_ids.
        """
        # Filter out None values before querying
        valid_ids = [aid for aid in arxiv_ids if aid]
        if not valid_ids:
            return set()
        try:
            db = await get_service_client()
            response = await (
                db.table("content_items")
                .select("arxiv_id")
                .in_("arxiv_id", valid_ids)
                .execute()
            )
            return {row["arxiv_id"] for row in response.data or [] if row.get("arxiv_id")}
        except Exception as e:
            logger.error(
                f"[Processor] Batch arxiv_id dedup query failed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return set()

    # -----------------------------------------------------------------------
    # Topic classification
    # -----------------------------------------------------------------------

    def classify_topic(self, title: str, full_content: str) -> str:
        """
        Classify content into a topic using keyword matching.

        Searches the combined title + full_content (lowercased) for keywords.
        Topics are checked in priority order (TOPIC_KEYWORDS dict order):
          Multimodal → Generative_AI → CV → RL → NLP → LLMs → General_AI

        Why this order? More specific topics first — a paper about image generation
        should be "Generative_AI" or "CV", not "LLMs" just because it uses transformers.

        Args:
            title:        Item title (from scraper)
            full_content: Abstract, description, or summary (from scraper)

        Returns:
            Topic string — one of the TOPIC_KEYWORDS keys or "General_AI"
        """
        # Combine title + content, lowercase for case-insensitive matching
        # Title gets double weight by including it twice — more signal per word
        search_text = f"{title} {title} {full_content}".lower()

        for topic, keywords in TOPIC_KEYWORDS.items():
            for keyword in keywords:
                if keyword in search_text:
                    return topic

        # No keywords matched — general AI content
        return "General_AI"

    # -----------------------------------------------------------------------
    # Difficulty detection
    # -----------------------------------------------------------------------

    def detect_difficulty(self, title: str, full_content: str) -> str:
        """
        Detect content difficulty using keyword matching.

        Checks Advanced keywords first, then Easy keywords.
        If neither matches, defaults to Intermediate.

        Logic:
          - Advanced: contains mathematical/theoretical terms
          - Easy: explicitly educational (survey, tutorial, overview)
          - Intermediate: everything else (most papers and blog posts)

        Args:
            title:        Item title
            full_content: Abstract or summary

        Returns:
            "Advanced", "Easy", or "Intermediate"
        """
        search_text = f"{title} {full_content}".lower()

        for difficulty, keywords in DIFFICULTY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in search_text:
                    return difficulty

        # Default — most research papers fall here
        return "Intermediate"

    # -----------------------------------------------------------------------
    # Attention score calculation
    # -----------------------------------------------------------------------

    def calculate_attention_score(
        self,
        source_name: str,
        published_at: Optional[str],
        metadata_json: Optional[dict],
    ) -> float:
        """
        Calculate attention score — determines feed ranking.

        Formula:
          attention_score = recency_boost + source_weight + citation_bonus

        Components:
          recency_boost:  50 if published <24h ago
                          30 if published <48h ago
                          10 if published <7 days ago
                          0  if older or unknown
          source_weight:  Fixed per source (arXiv=10, HuggingFace=8, blogs=7)
          citation_bonus: log10(citation_count + 1) * 5
                          (only for arXiv if citations available in metadata)

        Note: topic_match (up to 30 points) is set to 0 here.
        It will be added later when user preferences are linked to the feed.
        This score is the base ranking before personalization.

        Args:
            source_name:   e.g. "arXiv", "HuggingFace", "Anthropic"
            published_at:  ISO 8601 date string or None
            metadata_json: Dict from scraper, may contain citation_count

        Returns:
            Float attention score (higher = shown first in feed)
        """
        score = 0.0

        # --- Recency boost ---
        if published_at:
            try:
                # Parse ISO 8601 string back to datetime for comparison
                now = datetime.datetime.now(datetime.timezone.utc)
                pub_dt = datetime.datetime.fromisoformat(published_at)
                # Handle both naive (from our scrapers) and aware (future-proof)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                age = now - pub_dt

                if age.total_seconds() < 86400:       # < 24 hours
                    score += 50
                elif age.total_seconds() < 172800:    # < 48 hours
                    score += 30
                elif age.days < 7:                    # < 7 days
                    score += 10
                # else: score += 0 (older content gets no recency boost)

            except (ValueError, TypeError) as e:
                # Can't parse date — no recency boost, but don't crash
                logger.debug(f"[Processor] Could not parse published_at '{published_at}': {e}")

        # --- Source weight ---
        # Look up fixed weight by source_name, fallback to "default" (7) for blogs
        score += SOURCE_WEIGHTS.get(source_name, SOURCE_WEIGHTS["default"])

        # --- Citation bonus ---
        # Only available if scraper included citation_count in metadata_json
        # Currently arXiv RSS doesn't provide citations — reserved for future
        # (e.g. Semantic Scholar API enrichment in a later phase)
        citation_count = 0
        if metadata_json and isinstance(metadata_json, dict):
            citation_count = metadata_json.get("citation_count", 0) or 0

        if citation_count > 0:
            # log10 keeps this from dominating — a 1000-citation paper gets 15 bonus,
            # not 1000 bonus. Prevents old famous papers from burying new ones.
            score += math.log10(citation_count + 1) * 5

        return round(score, 2)

    # -----------------------------------------------------------------------
    # Main processing pipeline
    # -----------------------------------------------------------------------

    async def process_items(self, items: list[dict]) -> list[dict]:
        """
        Process a list of raw scraper items into DB-ready content items.

        For each item:
          1. Check if duplicate (source_url or arxiv_id already in DB) → skip if yes
          2. Classify topic via keyword rules
          3. Detect difficulty via keyword rules
          4. Calculate attention score
          5. Ensure all required DB fields are present with correct defaults

        Args:
            items: Raw list of dicts from any scraper (arXiv, HuggingFace, RSS blogs)

        Returns:
            List of processed dicts ready for DB insert + summarizer.
            Returns [] if all items are duplicates or input is empty.
            Never raises — all exceptions caught internally.
        """
        if not items:
            logger.info("[Processor] No items to process.")
            return []

        logger.info(f"[Processor] Processing {len(items)} raw items.")

        # Batch dedup — ONE query per field instead of N queries per item
        all_urls = [item.get("source_url", "") for item in items]
        all_arxiv_ids = [item.get("arxiv_id") for item in items]

        existing_urls = await self._get_existing_urls(all_urls)
        existing_arxiv_ids = await self._get_existing_arxiv_ids(all_arxiv_ids)

        processed = []
        skipped_dupes = 0
        errors = 0

        for item in items:
            try:
                source_url = item.get("source_url", "")
                arxiv_id = item.get("arxiv_id")

                if not source_url:
                    logger.warning("[Processor] Item missing source_url — skipping.")
                    errors += 1
                    continue

                # Check against batch-fetched sets — no DB call per item
                if source_url in existing_urls:
                    logger.debug(f"[Processor] Duplicate URL — skipping: {source_url}")
                    skipped_dupes += 1
                    continue

                if arxiv_id and arxiv_id in existing_arxiv_ids:
                    logger.debug(f"[Processor] Duplicate arXiv ID — skipping: {arxiv_id}")
                    skipped_dupes += 1
                    continue

                # --- Step 2: Topic classification ---
                title = item.get("title", "")
                full_content = item.get("full_content", "")
                topic = self.classify_topic(title, full_content)

                # --- Step 3: Difficulty detection ---
                difficulty = self.detect_difficulty(title, full_content)

                # --- Step 4: Attention score ---
                attention_score = self.calculate_attention_score(
                    source_name=item.get("source_name", ""),
                    published_at=item.get("published_at"),
                    metadata_json=item.get("metadata_json"),
                )

                # --- Step 5: Build final processed item ---
                # Merge scraper fields + processor-computed fields
                # Explicit field mapping ensures schema consistency
                processed_item = {
                    # Fields from scraper (pass through unchanged)
                    "title":        title,
                    "source_url":   source_url,
                    "source_name":  item.get("source_name", ""),
                    "content_type": item.get("content_type", ""),
                    "arxiv_id":     arxiv_id,
                    "authors":      item.get("authors", []),
                    "full_content": full_content,
                    "published_at": item.get("published_at"),
                    "metadata_json": item.get("metadata_json", {}),

                    # Fields computed by processor
                    "topic":            topic,
                    "difficulty":       difficulty,
                    "attention_score":  attention_score,

                    # Fields with fixed defaults at this stage
                    # summarizer sets is_summarized=True after generating summary
                    # scheduler sets is_released=True for Pro users / 4AM batch
                    "summary":        None,   # Filled by summarizer
                    "is_summarized":  False,
                    "is_released":    False,
                    "has_peeler":     False,
                    "peel_count":     0,
                }

                processed.append(processed_item)

            except Exception as e:
                # Never let one bad item crash the whole batch
                logger.error(
                    f"[Processor] Unexpected error processing item "
                    f"'{item.get('source_url', 'unknown')}': "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )
                errors += 1
                continue

        logger.info(
            f"[Processor] Done. "
            f"{len(processed)} new | {skipped_dupes} duplicates | {errors} errors"
        )

        return processed
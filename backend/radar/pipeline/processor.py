# radar/pipeline/processor.py
#
# Processes raw scraper output into DB-ready content items.
# ZERO AI COST — pure keyword rules.
#
# Steps per item:
#   1. Deduplication — skip if source_url or arxiv_id already in DB
#   2. Topic classification — keyword scoring (best match wins)
#   3. Difficulty detection — keyword rules (papers only)
#   4. Attention score — freshness + source trust + impact + novelty
#   5. Signal label — human label from score ("High Signal" etc.)
#   6. Key tags — impact keywords found in content
#   7. Field normalization — defaults for all DB columns

import datetime
import logging
import math
from typing import Optional

from radar.core.database import get_service_client
from config import (
    TOPIC_MAP,
    DIFFICULTY_KEYWORDS,
    ADVANCED_THRESHOLD,
    SIGNAL_HIGH_THRESHOLD,
    SIGNAL_PEEL_THRESHOLD,
    SIGNAL_WATCHING_THRESHOLD,
)

logger = logging.getLogger("paperlens.radar.pipeline.processor")

# ---------------------------------------------------------------------------
# IMPACT KEYWORDS — detect high-signal content
# Each keyword found adds to impact_bonus (capped at 20)
# These indicate papers/posts with real-world significance
# ---------------------------------------------------------------------------
IMPACT_KEYWORDS: list[str] = [
    "benchmark", "state-of-the-art", "sota", "outperforms",
    "efficient", "reasoning", "long-context", "agent", "multimodal",
    "open-source", "open source", "dataset", "architecture",
    "breakthrough", "novel", "new model", "instruction", "alignment",
    "safety", "scalable", "real-time", "zero-shot", "few-shot",
    "chain-of-thought", "retrieval", "fine-tuning", "finetune",
    "we introduce", "we present", "we propose", "we release",
]
IMPACT_BONUS_PER_KW = 3    # score per keyword found
IMPACT_BONUS_CAP    = 20   # max total impact bonus

# ---------------------------------------------------------------------------
# NOVELTY KEYWORDS — detect first-of-kind releases
# ---------------------------------------------------------------------------
NOVELTY_KEYWORDS: dict[str, int] = {
    "we introduce":    5,
    "we present":      5,
    "we propose":      5,
    "we release":      4,
    "open-source":     4,
    "open source":     3,
    "github.com":      3,
    "new benchmark":   3,
    "new dataset":     3,
    "new architecture": 3,
    "new model":       3,
}
NOVELTY_CAP = 10

# ---------------------------------------------------------------------------
# SOURCE TRUST SCORES — different labs have different signal value
# ---------------------------------------------------------------------------
SOURCE_TRUST: dict[str, float] = {
    "OpenAI":          20.0,
    "Anthropic":       20.0,
    "Google DeepMind": 20.0,
    "Meta AI":         18.0,
    "Google AI":       17.0,
    "Mistral AI":      16.0,
    "arXiv":           18.0,
    "HuggingFace":     12.0,
}
SOURCE_TRUST_DEFAULT = 8.0

# ---------------------------------------------------------------------------
# FRESHNESS TIERS (score out of 50)
# ---------------------------------------------------------------------------
FRESHNESS_TIERS = [
    (6    * 3600,  50.0),   # < 6 hours
    (24   * 3600,  40.0),   # < 24 hours
    (48   * 3600,  25.0),   # < 48 hours
    (72   * 3600,  15.0),   # < 72 hours
    (7    * 86400,  5.0),   # < 7 days
]


class Processor:
    """
    Processes raw scraper items into DB-ready content items.

    All classification is keyword-based — zero AI cost, zero latency.
    The LLM (Summarizer) only runs after items are inserted into the DB.
    """

    def __init__(self):
        logger.info("[Processor] Initialized.")

    # -----------------------------------------------------------------------
    # Batch deduplication — ONE DB query per field, not N queries per item
    # -----------------------------------------------------------------------

    async def _get_existing_urls(self, urls: list[str]) -> set[str]:
        """Batch check: return set of source_urls already in content_items.
        Batches into chunks of 50 to avoid URL query-too-long errors."""
        if not urls:
            return set()
        existing: set[str] = set()
        CHUNK = 50
        try:
            db = await get_service_client()
            for i in range(0, len(urls), CHUNK):
                batch = urls[i : i + CHUNK]
                resp = await (
                    db.table("content_items")
                    .select("source_url")
                    .in_("source_url", batch)
                    .execute()
                )
                existing.update(row["source_url"] for row in resp.data or [])
            return existing
        except Exception as e:
            logger.error(f"[Processor] URL dedup query failed: {e}", exc_info=True)
            return set()

    async def _get_existing_arxiv_ids(self, ids: list[str]) -> set[str]:
        """Batch check: return set of arxiv_ids already in content_items."""
        valid = [aid for aid in ids if aid]
        if not valid:
            return set()
        try:
            db = await get_service_client()
            resp = await (
                db.table("content_items")
                .select("arxiv_id")
                .in_("arxiv_id", valid)
                .execute()
            )
            return {row["arxiv_id"] for row in resp.data or [] if row.get("arxiv_id")}
        except Exception as e:
            logger.error(f"[Processor] arXiv ID dedup query failed: {e}", exc_info=True)
            return set()

    # -----------------------------------------------------------------------
    # Topic classification
    # -----------------------------------------------------------------------

    def classify_topic(self, title: str, full_content: str) -> str:
        """
        Classify content into a topic using TOPIC_MAP from config.py.
        Title gets 3× weight (more descriptive than abstract).
        Returns the topic with the highest keyword match score.
        """
        # Title 3× because it's more signal-dense
        search_text = (f"{title} " * 3 + full_content).lower()

        topic_scores: dict[str, int] = {}
        for topic, keywords in TOPIC_MAP.items():
            score = 0
            for kw in keywords:
                if kw.lower() in search_text:
                    score += len(kw.split())   # multi-word keywords score higher
            if score > 0:
                topic_scores[topic] = score

        if not topic_scores:
            return "Other"
        return max(topic_scores, key=topic_scores.get)

    # -----------------------------------------------------------------------
    # Difficulty detection (papers only — blogs/models always Intermediate)
    # -----------------------------------------------------------------------

    def detect_difficulty(self, title: str, full_content: str, content_type: str) -> str:
        """
        Detect difficulty level for papers.
        Non-papers always return "Intermediate" (no meaningful difficulty).

        Rules (from DIFFICULTY_KEYWORDS in config.py):
          ADVANCED_THRESHOLD+ advanced keywords → "Advanced"
          1+ easy keywords                      → "Easy"
          Everything else                       → "Intermediate"
        """
        if content_type != "paper":
            return "Intermediate"

        text = (title + " " + full_content).lower()

        advanced_count = sum(
            1 for kw in DIFFICULTY_KEYWORDS["advanced"]
            if kw.lower() in text
        )
        easy_count = sum(
            1 for kw in DIFFICULTY_KEYWORDS["easy"]
            if kw.lower() in text
        )

        if advanced_count >= ADVANCED_THRESHOLD:
            return "Advanced"
        if easy_count >= 1:
            return "Easy"
        return "Intermediate"

    # -----------------------------------------------------------------------
    # Key tags extraction
    # -----------------------------------------------------------------------

    def extract_key_tags(self, title: str, full_content: str) -> list[str]:
        """
        Find which IMPACT_KEYWORDS appear in this item's text.
        Returns up to 6 matching keywords — stored as key_tags in DB.
        Used by frontend for quick visual scanning.
        """
        search_text = (title + " " + full_content).lower()
        found = [
            kw for kw in IMPACT_KEYWORDS
            if kw in search_text
        ]
        # Deduplicate while preserving order, cap at 6
        seen = set()
        unique = []
        for kw in found:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
            if len(unique) >= 6:
                break
        return unique

    # -----------------------------------------------------------------------
    # Attention score
    # -----------------------------------------------------------------------

    def calculate_attention_score(
        self,
        source_name: str,
        published_at: Optional[str],
        title: str,
        full_content: str,
        metadata_json: Optional[dict],
    ) -> float:
        """
        Calculate attention score (0–100).

        Components:
          freshness    (0–50): recency-based tiers
          source_trust (0–20): fixed per source
          impact_bonus (0–20): impact keyword count
          novelty_bonus(0–10): novelty/release keyword bonuses
          citation_bonus(0–10): log scale from metadata

        Score is capped at 100.
        """
        score = 0.0
        search_text = (title + " " + full_content).lower()

        # --- Freshness ---
        if published_at:
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                pub = datetime.datetime.fromisoformat(published_at)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=datetime.timezone.utc)
                age_seconds = (now - pub).total_seconds()

                freshness = 0.0
                for threshold, pts in FRESHNESS_TIERS:
                    if age_seconds < threshold:
                        freshness = pts
                        break
                score += freshness

            except (ValueError, TypeError) as e:
                logger.debug(f"[Processor] Could not parse published_at '{published_at}': {e}")

        # --- Source trust ---
        score += SOURCE_TRUST.get(source_name, SOURCE_TRUST_DEFAULT)

        # --- Impact bonus (capped) ---
        impact_total = 0.0
        for kw in IMPACT_KEYWORDS:
            if kw in search_text:
                impact_total += IMPACT_BONUS_PER_KW
                if impact_total >= IMPACT_BONUS_CAP:
                    break
        score += min(impact_total, IMPACT_BONUS_CAP)

        # --- Novelty bonus (capped) ---
        novelty_total = 0.0
        for kw, pts in NOVELTY_KEYWORDS.items():
            if kw in search_text:
                novelty_total += pts
        score += min(novelty_total, NOVELTY_CAP)

        # --- Citation bonus (if available — e.g. from Semantic Scholar enrichment) ---
        citation_count = 0
        if metadata_json and isinstance(metadata_json, dict):
            citation_count = metadata_json.get("citation_count", 0) or 0
        if citation_count > 0:
            # log10 scale — 1000 citations → 15 bonus, not 1000 bonus
            score += min(math.log10(citation_count + 1) * 3.3, 10.0)

        # HuggingFace likes/downloads also boost score slightly
        if metadata_json and isinstance(metadata_json, dict):
            likes     = metadata_json.get("likes", 0) or 0
            downloads = metadata_json.get("downloads", 0) or 0
            if likes > 0:
                score += min(math.log10(likes + 1) * 2, 5.0)
            if downloads > 100:
                score += min(math.log10(downloads) * 1.5, 5.0)

        return round(min(score, 100.0), 2)

    # -----------------------------------------------------------------------
    # Signal label
    # -----------------------------------------------------------------------

    def assign_signal_label(
        self, attention_score: float, content_type: str
    ) -> str:
        """
        Assign a human-readable signal label based on score.
        Never show raw numbers to users — these labels are what the UI shows.

        Rules (thresholds from config.py):
          >= SIGNAL_HIGH_THRESHOLD (75)          → "High Signal"
          >= SIGNAL_PEEL_THRESHOLD (60) + paper  → "Worth Peeling"
          >= SIGNAL_WATCHING_THRESHOLD (45)       → "Worth Watching"
          else                                    → "Quick Skim"
        """
        if attention_score >= SIGNAL_HIGH_THRESHOLD:
            return "High Signal"
        if content_type == "paper" and attention_score >= SIGNAL_PEEL_THRESHOLD:
            return "Worth Peeling"
        if attention_score >= SIGNAL_WATCHING_THRESHOLD:
            return "Worth Watching"
        return "Quick Skim"

    # -----------------------------------------------------------------------
    # Main processing pipeline
    # -----------------------------------------------------------------------

    async def process_items(self, items: list[dict]) -> list[dict]:
        """
        Process a batch of raw scraper items into DB-ready content items.

        For each item:
          1. Skip duplicates (source_url or arxiv_id already in DB)
          2. Classify topic
          3. Detect difficulty
          4. Extract key_tags
          5. Calculate attention_score
          6. Assign signal_label
          7. Normalize all DB fields with defaults

        Returns only new items ready for insert. Never raises.
        """
        if not items:
            return []

        logger.info(f"[Processor] Processing {len(items)} raw items.")

        # Batch dedup — one query per field
        all_urls      = [item.get("source_url", "") for item in items]
        all_arxiv_ids = [item.get("arxiv_id") for item in items]

        existing_urls      = await self._get_existing_urls(all_urls)
        existing_arxiv_ids = await self._get_existing_arxiv_ids(all_arxiv_ids)

        processed    = []
        skipped_dupes = 0
        errors        = 0

        for item in items:
            try:
                source_url = item.get("source_url", "")
                arxiv_id   = item.get("arxiv_id")

                if not source_url:
                    logger.warning("[Processor] Item missing source_url — skipping.")
                    errors += 1
                    continue

                if source_url in existing_urls:
                    logger.debug(f"[Processor] Duplicate URL: {source_url}")
                    skipped_dupes += 1
                    continue

                if arxiv_id and arxiv_id in existing_arxiv_ids:
                    logger.debug(f"[Processor] Duplicate arXiv ID: {arxiv_id}")
                    skipped_dupes += 1
                    continue

                # --- Classification ---
                title        = item.get("title", "")
                full_content = item.get("full_content", "")
                content_type = item.get("content_type", "")

                topic       = self.classify_topic(title, full_content)
                difficulty  = self.detect_difficulty(title, full_content, content_type)
                key_tags    = self.extract_key_tags(title, full_content)

                attention_score = self.calculate_attention_score(
                    source_name  = item.get("source_name", ""),
                    published_at = item.get("published_at"),
                    title        = title,
                    full_content = full_content,
                    metadata_json= item.get("metadata_json"),
                )
                signal_label = self.assign_signal_label(attention_score, content_type)

                # --- Build DB-ready item ---
                processed_item = {
                    # From scraper (unchanged)
                    "title":        title,
                    "source_url":   source_url,
                    "source_name":  item.get("source_name", ""),
                    "content_type": content_type,
                    "arxiv_id":     arxiv_id,
                    "authors":      item.get("authors", []),
                    "full_content": full_content,
                    "published_at": item.get("published_at"),
                    "metadata_json": item.get("metadata_json", {}),

                    # Computed by processor
                    "topic":           topic,
                    "difficulty":      difficulty,
                    "key_tags":        key_tags,
                    "attention_score": attention_score,
                    "signal_label":    signal_label,

                    # Defaults — updated by summarizer / scheduler
                    "summary":         None,
                    "why_it_matters":  None,
                    "is_summarized":   False,
                    "is_released":     False,
                    "has_peeler":      content_type == "paper",  # papers can be peeled
                    "peel_count":      0,
                    "read_count":      0,
                    "save_count":      0,
                }

                processed.append(processed_item)

            except Exception as e:
                logger.error(
                    f"[Processor] Error processing '{item.get('source_url', 'unknown')}': "
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

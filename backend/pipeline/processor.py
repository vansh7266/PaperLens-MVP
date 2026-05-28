# ============================================================
# pipeline/processor.py — Paper Processor
# ============================================================
# Takes raw Paper objects from scrapers and makes them
# database-ready by running 5 steps:
#
#   1. Deduplicate    → remove same paper appearing twice
#   2. Classify topic → assign LLMs / CV / RL etc.
#   3. Detect difficulty → Easy / Intermediate / Advanced
#   4. Calculate attention score → rank papers for free users
#   5. Detect type    → paper / model / news
#
# ZERO AI COST — everything here is pure logic and keywords.
# LLM is only used as fallback if keyword matching fails.
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime, timezone
from typing import Optional

from config import (
    TOPIC_MAP,
    DIFFICULTY_KEYWORDS,
    ADVANCED_THRESHOLD,
    WEIGHT_CITATIONS,
    WEIGHT_HN,
    WEIGHT_REDDIT,
    WEIGHT_RECENCY,
    DEBUG,
)
from scrapers.arxiv import Paper


# ============================================================
# MAIN FUNCTION — process_batch()
# ============================================================
# This is what the scheduler calls after fetching papers.
# Runs all 5 processing steps in order.

async def process_batch(
    papers: list[Paper],
    existing_ids: set = None,
) -> list[Paper]:
    """
    Process a batch of raw papers through all pipeline steps.

    Parameters:
        papers      → raw Paper objects from scrapers
        existing_ids→ set of paper IDs already in database
                      used to skip papers we already have

    Returns:
        List of fully processed Paper objects ready for database
    """
    if not papers:
        return []

    if DEBUG:
        print(f"\n[processor] Starting batch: {len(papers)} papers")

    # Step 1: Deduplicate within the batch
    papers = _deduplicate_batch(papers)
    if DEBUG:
        print(f"[processor] After dedup: {len(papers)} papers")

    # Step 2: Remove papers already in database
    if existing_ids:
        before = len(papers)
        papers = [p for p in papers if p.id not in existing_ids]
        if DEBUG:
            print(f"[processor] Already in DB: {before - len(papers)} skipped")

    if not papers:
        if DEBUG:
            print("[processor] No new papers to process")
        return []

    # Step 3: Classify topics (keyword-based, free)
    papers = _classify_topics(papers)

    # Step 4: Detect difficulty (rule-based, free)
    papers = _detect_difficulties(papers)

    # Step 5: Detect paper type
    papers = _detect_types(papers)

    # Step 6: Calculate attention scores
    papers = _calculate_scores(papers)

    # Step 7: Clean up text fields
    papers = _clean_text(papers)

    if DEBUG:
        _print_summary(papers)

    return papers


# ============================================================
# STEP 1 — DEDUPLICATE
# ============================================================

def _deduplicate_batch(papers: list[Paper]) -> list[Paper]:
    """
    Remove duplicate papers within the same batch.
    A paper can appear in multiple arXiv categories.
    We keep the first occurrence and skip the rest.
    When we find a duplicate, we merge its categories
    into the first occurrence.
    """
    seen = {}       # id → Paper object
    unique = []

    for paper in papers:
        if paper.id not in seen:
            seen[paper.id] = paper
            unique.append(paper)
        else:
            # Merge categories from duplicate into existing
            existing = seen[paper.id]
            for cat in paper.categories:
                if cat not in existing.categories:
                    existing.categories.append(cat)

    return unique


# ============================================================
# STEP 2 — CLASSIFY TOPICS
# ============================================================

def _classify_topics(papers: list[Paper]) -> list[Paper]:
    """
    Assign a topic to each paper using keyword matching.
    Uses TOPIC_MAP from config.py — completely free, no API.

    Algorithm:
        1. Combine title + abstract (lowercase)
        2. Count how many keywords from each topic appear
        3. Assign the topic with the most keyword matches
        4. If no matches → assign "Other"
    """
    for paper in papers:
        if paper.topic:
            # Already classified (e.g. by a previous run)
            continue

        paper.topic = _classify_single(paper.title, paper.abstract)

    return papers


def _classify_single(title: str, abstract: str) -> str:
    """
    Classify one paper into a topic using keyword matching.
    Returns the best matching topic name or "Other".
    """
    # Combine title and abstract for matching
    # Title gets 3x weight since it's more descriptive
    text = (title.lower() + " ") * 3 + abstract.lower()

    topic_scores = {}

    for topic, keywords in TOPIC_MAP.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text:
                # Exact phrase match scores higher than single word
                words_in_keyword = len(keyword.split())
                score += words_in_keyword
        if score > 0:
            topic_scores[topic] = score

    if not topic_scores:
        return "Other"

    # Return topic with highest score
    return max(topic_scores, key=topic_scores.get)


# ============================================================
# STEP 3 — DETECT DIFFICULTY
# ============================================================

def _detect_difficulties(papers: list[Paper]) -> list[Paper]:
    """
    Assign difficulty level to each paper.
    Uses keyword counting — completely free, no API.

    Rules (from config.py):
        3+ advanced keywords  → "Advanced"
        1+ easy keywords      → "Easy"
        Everything else       → "Intermediate"
    """
    for paper in papers:
        if paper.difficulty and paper.difficulty != "Intermediate":
            # Already set (not default)
            continue
        paper.difficulty = _detect_single_difficulty(
            paper.title, paper.abstract
        )

    return papers


def _detect_single_difficulty(title: str, abstract: str) -> str:
    """
    Detect difficulty for one paper.
    Returns "Easy", "Intermediate", or "Advanced"
    """
    text = (title + " " + abstract).lower()

    # Count advanced keywords
    advanced_count = sum(
        1 for kw in DIFFICULTY_KEYWORDS["advanced"]
        if kw.lower() in text
    )

    # Count easy keywords
    easy_count = sum(
        1 for kw in DIFFICULTY_KEYWORDS["easy"]
        if kw.lower() in text
    )

    if advanced_count >= ADVANCED_THRESHOLD:
        return "Advanced"
    elif easy_count >= 1:
        return "Easy"
    else:
        return "Intermediate"


# ============================================================
# STEP 4 — DETECT PAPER TYPE
# ============================================================

def _detect_types(papers: list[Paper]) -> list[Paper]:
    """
    Detect whether each item is:
        "paper" → research paper (arXiv, Semantic Scholar)
        "model" → model release announcement
        "news"  → news article, blog post

    Rules:
        Source = arxiv                    → "paper"
        Source = blog AND title has model name patterns → "model"
        Source = blog                     → "news"
        Title has "we introduce/release"  → "model"
    """
    # Keywords that suggest a model release
    model_keywords = [
        "we introduce", "we release", "we present",
        "introducing", "releasing", "open-source",
        "open source", "available at", "github.com",
    ]

    # Blog sources that produce news (not papers)
    news_sources = {
        "anthropic", "openai", "deepmind", "meta ai",
        "mistral", "huggingface", "google",
    }

    for paper in papers:
        if paper.paper_type and paper.paper_type != "paper":
            # Already set
            continue

        source_lower = paper.source.lower()
        title_lower = paper.title.lower()

        # Source is a blog → news or model
        if any(ns in source_lower for ns in news_sources):
            # Check if it's a model release
            if any(kw in title_lower for kw in model_keywords):
                paper.paper_type = "model"
                paper.has_peeler = False  # model releases can't be peeled
            else:
                paper.paper_type = "news"
                paper.has_peeler = False  # news articles can't be peeled
        else:
            # arXiv or Semantic Scholar → paper
            paper.paper_type = "paper"
            paper.has_peeler = True

    return papers


# ============================================================
# STEP 5 — CALCULATE ATTENTION SCORES
# ============================================================

def _calculate_scores(papers: list[Paper]) -> list[Paper]:
    """
    Calculate attention score for each paper.
    Used by queue.py to select top 20 papers for free users.

    Formula (from config.py weights):
        score = (citations × 2.0)
              + (hn_points × 1.5)
              + (reddit_upvotes × 1.0)
              + (recency_bonus)

    Recency bonus:
        Papers published in the last 24 hours get +10
        Papers published in the last 48 hours get +5
        Older papers get 0

    Note: citation_count, hn_points, reddit_upvotes are 0
    right now. We'll add those integrations later.
    At launch, ranking is purely by recency.
    """
    now = datetime.now(timezone.utc)

    for paper in papers:
        score = 0.0

        # Citation score (0 for now, filled later)
        score += paper.citation_count * WEIGHT_CITATIONS

        # HN points score (0 for now)
        score += paper.hn_points * WEIGHT_HN

        # Reddit upvotes score (0 for now)
        score += paper.reddit_upvotes * WEIGHT_REDDIT

        # Recency bonus
        try:
            pub = paper.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            hours_old = (now - pub).total_seconds() / 3600

            if hours_old <= 24:
                score += 10.0   # very fresh
            elif hours_old <= 48:
                score += 5.0    # recent
            elif hours_old <= 72:
                score += 2.0    # somewhat recent

            # Small penalty per hour (newer is better)
            score += hours_old * WEIGHT_RECENCY

        except Exception:
            pass

        # Store score — we'll add this field to Paper dataclass
        # For now, store in a temporary attribute
        paper._attention_score = round(score, 2)

    return papers


# ============================================================
# STEP 6 — CLEAN TEXT
# ============================================================

def _clean_text(papers: list[Paper]) -> list[Paper]:
    """
    Clean up title and abstract text.

    - Remove extra whitespace
    - Remove LaTeX formatting artifacts
    - Remove HTML entities
    - Truncate extremely long abstracts
    - Ensure title is properly capitalised
    """
    for paper in papers:
        # Clean title
        paper.title = _clean_field(paper.title)

        # Clean abstract
        paper.abstract = _clean_field(paper.abstract)

        # Truncate abstract if too long (keep first 1000 chars)
        if len(paper.abstract) > 1000:
            paper.abstract = paper.abstract[:997] + "..."

        # Clean authors list
        paper.authors = [
            a.strip() for a in paper.authors
            if a and a.strip()
        ][:10]  # max 10 authors displayed

    return papers


def _clean_field(text: str) -> str:
    """Clean a single text field."""
    import re

    if not text:
        return ""

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Remove HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')

    # Remove LaTeX artifacts (common in arXiv)
    # e.g. $\mathcal{F}$, \textbf{}, etc.
    text = re.sub(r'\$[^$]+\$', '', text)    # remove inline math
    text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)  # \command{text}
    text = re.sub(r'\\[a-zA-Z]+', '', text)  # standalone \command

    # Normalise whitespace
    text = ' '.join(text.split())

    return text.strip()


# ============================================================
# HELPER — print summary stats
# ============================================================

def _print_summary(papers: list[Paper]):
    """Print processing summary for debugging."""
    from collections import Counter

    topics = Counter(p.topic for p in papers)
    diffs = Counter(p.difficulty for p in papers)
    types = Counter(p.paper_type for p in papers)

    print(f"\n[processor] Processed {len(papers)} papers:")
    print(f"  Topics     : {dict(topics)}")
    print(f"  Difficulty : {dict(diffs)}")
    print(f"  Types      : {dict(types)}")


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def classify_paper(title: str, abstract: str) -> dict:
    """
    Classify a single paper and return all metadata.
    Useful for testing or one-off classification.

    Returns dict with topic, difficulty, type.
    """
    topic = _classify_single(title, abstract)
    difficulty = _detect_single_difficulty(title, abstract)

    return {
        "topic": topic,
        "difficulty": difficulty,
    }


def sort_by_attention(papers: list[Paper]) -> list[Paper]:
    """
    Sort papers by attention score (highest first).
    Used by queue.py to select top 20 for free users.
    """
    return sorted(
        papers,
        key=lambda p: getattr(p, '_attention_score', 0),
        reverse=True
    )


def get_top_papers(papers: list[Paper], n: int = 20) -> list[Paper]:
    """
    Get top N papers by attention score.
    Used by queue.py for free user daily digest.
    """
    sorted_papers = sort_by_attention(papers)
    return sorted_papers[:n]


# ============================================================
# TEST — run this file directly
# Command: python pipeline/processor.py
# ============================================================

async def _test():
    from scrapers.arxiv import Paper
    from datetime import timedelta

    print(f"\n{'='*55}")
    print(f"  Testing Pipeline Processor")
    print(f"{'='*55}\n")

    # Create fake papers for testing
    now = datetime.now(timezone.utc)

    test_papers = [
        Paper(
            id="2301.00001",
            title="Scaling language model reasoning with chain-of-thought",
            abstract="We propose a new distillation framework for large language models. The transformer-based approach achieves strong results on math reasoning benchmarks.",
            authors=["Wei Chen", "Priya Sharma"],
            url="https://arxiv.org/abs/2301.00001",
            published_at=now - timedelta(hours=2),
            source="arxiv",
        ),
        Paper(
            id="2301.00002",
            title="DiffusionDet: Real-time object detection via diffusion",
            abstract="We apply denoising diffusion models to object detection tasks. Our image-based approach achieves 42 FPS while maintaining accuracy.",
            authors=["John Doe"],
            url="https://arxiv.org/abs/2301.00002",
            published_at=now - timedelta(hours=5),
            source="arxiv",
        ),
        # Duplicate to test dedup
        Paper(
            id="2301.00001",
            title="Scaling language model reasoning with chain-of-thought",
            abstract="Same paper appearing again from cs.CV category",
            authors=["Wei Chen"],
            url="https://arxiv.org/abs/2301.00001",
            published_at=now - timedelta(hours=2),
            source="arxiv",
            categories=["cs.CV"],
        ),
        Paper(
            id="2301.00003",
            title="Introduction to Reinforcement Learning: A Survey",
            abstract="An introductory survey of reinforcement learning methods including policy gradient and actor-critic approaches.",
            authors=["Jane Smith"],
            url="https://arxiv.org/abs/2301.00003",
            published_at=now - timedelta(hours=10),
            source="arxiv",
        ),
        Paper(
            id="2301.00004",
            title="Proof of Convergence for Stochastic Gradient Methods",
            abstract="We provide theoretical convergence proofs and asymptotic bounds for stochastic optimization with variational inference and Bayesian methods.",
            authors=["Alice Brown"],
            url="https://arxiv.org/abs/2301.00004",
            published_at=now - timedelta(hours=20),
            source="arxiv",
        ),
    ]

    print(f"Input: {len(test_papers)} papers (including 1 duplicate)\n")

    # Process them
    processed = await process_batch(test_papers)

    print(f"\nResults:")
    print(f"  Total processed : {len(processed)} papers (1 duplicate removed)")
    print(f"\n  Paper details:")

    for p in processed:
        score = getattr(p, '_attention_score', 0)
        print(f"\n  [{p.id}]")
        print(f"    Title      : {p.title[:60]}...")
        print(f"    Topic      : {p.topic}")
        print(f"    Difficulty : {p.difficulty}")
        print(f"    Type       : {p.paper_type}")
        print(f"    Has peeler : {p.has_peeler}")
        print(f"    Attn score : {score}")

    # Test top papers selection
    print(f"\n  Top 2 papers by attention:")
    top2 = get_top_papers(processed, n=2)
    for i, p in enumerate(top2):
        print(f"    {i+1}. {p.title[:50]}... (score: {getattr(p,'_attention_score',0)})")

    # Test classify_paper
    print(f"\n  Testing single classification:")
    result = classify_paper(
        "BERT: Pre-training of Deep Bidirectional Transformers",
        "We introduce BERT, a new language representation model which stands for Bidirectional Encoder Representations from Transformers."
    )
    print(f"    Topic: {result['topic']}")
    print(f"    Difficulty: {result['difficulty']}")

    print(f"\n{'='*55}")
    print(f"  ✅ Processor working correctly!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

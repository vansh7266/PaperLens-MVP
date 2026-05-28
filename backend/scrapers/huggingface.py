# ============================================================
# scrapers/huggingface.py — HuggingFace Model Scraper
# ============================================================
# Fetches new model releases from HuggingFace Hub.
# HuggingFace is the world's largest open-source AI model repo.
# When Llama 4, Mistral, Phi etc. get released, they appear here.
#
# API: https://huggingface.co/api/models (free, no key needed)
#
# What we fetch:
#   - New/updated model releases
#   - Filtered to popular AI categories
#   - Sorted by most recently modified
#
# paper_type = "model", has_peeler = False
# Downloads + likes used for attention score ranking
# ============================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional

from config import DEBUG
from scrapers.arxiv import Paper


# ============================================================
# HUGGINGFACE API SETTINGS
# ============================================================

HF_API_BASE = "https://huggingface.co/api"

# Model categories we care about
# These are HuggingFace pipeline tags
HF_CATEGORIES = [
    "text-generation",          # LLMs, chat models
    "text2text-generation",     # instruction-following models
    "image-generation",         # diffusion models, image gen
    "multimodal",               # vision-language models
    "text-to-image",            # image generation
    "image-to-text",            # captioning, VQA
]

# Minimum likes to include a model (filters out noise)
MIN_LIKES = 10

# Minimum downloads to include
MIN_DOWNLOADS = 100


# ============================================================
# MAIN FUNCTION — fetch_new_models()
# ============================================================

async def fetch_new_models(
    max_per_category: int = 10,
) -> list[Paper]:
    """
    Fetch recently released/updated models from HuggingFace.
    Called by scheduler every 5 minutes.

    Returns:
        List of Paper objects with paper_type="model"
    """
    all_models = []
    seen_ids = set()

    print(f"\n🤗 Fetching HuggingFace models ({len(HF_CATEGORIES)} categories)...")

    async with httpx.AsyncClient(timeout=20.0) as client:
        for category in HF_CATEGORIES:
            try:
                models = await _fetch_category(
                    client,
                    category,
                    max_per_category,
                )

                # Deduplicate
                new_models = []
                for m in models:
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        new_models.append(m)

                all_models.extend(new_models)
                print(f"  ✅ {category:25} → {len(new_models)} models")

                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"  ❌ {category:25} → Error: {str(e)[:50]}")
                continue

    print(f"\n  📦 Total HF models: {len(all_models)}\n")
    return all_models


# ============================================================
# FETCH ONE CATEGORY
# ============================================================

async def _fetch_category(
    client: httpx.AsyncClient,
    category: str,
    limit: int,
) -> list[Paper]:
    """
    Fetch models from one HuggingFace category.
    """
    params = {
        "sort":      "lastModified",  # newest first
        "direction": -1,              # descending
        "limit":     limit * 3,       # fetch extra, filter later
        "filter":    category,
        "full":      "false",         # don't need full model card
    }

    url = f"{HF_API_BASE}/models"

    if DEBUG:
        print(f"  [hf] Fetching: {url}?filter={category}")

    response = await client.get(url, params=params)
    response.raise_for_status()

    data = response.json()
    papers = []

    for model_data in data:
        try:
            paper = _model_to_paper(model_data)
            if paper:
                papers.append(paper)
        except Exception as e:
            if DEBUG:
                print(f"  [hf] Model parse error: {e}")
            continue

    # Apply quality filters
    papers = _filter_models(papers)

    return papers[:limit]


# ============================================================
# CONVERT MODEL DATA TO PAPER OBJECT
# ============================================================

def _model_to_paper(model_data: dict) -> Optional[Paper]:
    """
    Convert HuggingFace API model data to a Paper object.

    HF model data structure:
    {
        "modelId": "meta-llama/Llama-4-Scout",
        "author":  "meta-llama",
        "downloads": 500000,
        "likes":     12500,
        "tags":      ["text-generation", "llama", "pytorch"],
        "lastModified": "2025-03-22T10:00:00.000Z",
        "private": false
    }
    """
    model_id = model_data.get("modelId", "")
    if not model_id:
        return None

    # Skip private models
    if model_data.get("private", False):
        return None

    # Extract fields
    author    = model_data.get("author", "Unknown")
    downloads = model_data.get("downloads", 0)
    likes     = model_data.get("likes", 0)
    tags      = model_data.get("tags", [])
    modified  = model_data.get("lastModified", "")

    # Build readable title from model ID
    # "meta-llama/Llama-4-Scout" → "Llama-4-Scout by meta-llama"
    model_name = model_id.split("/")[-1] if "/" in model_id else model_id
    title = f"{model_name} by {author}"

    # Build description
    tag_str = ", ".join(t for t in tags[:5] if not t.startswith("arxiv"))
    description = (
        f"New model release on HuggingFace. "
        f"Tags: {tag_str}. "
        f"Downloads: {downloads:,}. "
        f"Likes: {likes:,}."
    )

    # Build URL
    url = f"https://huggingface.co/{model_id}"

    # Parse date
    published_at = _parse_hf_date(modified)

    # Unique ID — use the model_id but make it safe
    safe_id = f"hf_{model_id.replace('/', '_').replace('.', '_')}"

    # Detect topic from tags
    topic = _detect_topic_from_tags(tags, title)

    # Use downloads for attention score (replaces citations)
    # Normalise: 100k downloads ≈ 50 citations equivalent
    attention_proxy = (downloads / 2000) + (likes / 100)

    paper = Paper(
        id=safe_id,
        title=title,
        abstract=description,
        authors=[author],
        url=url,
        published_at=published_at,
        source="huggingface",
        source_id=model_id,
        paper_type="model",
        has_peeler=False,
        topic=topic,
        difficulty="Easy",
        categories=tags[:5],
    )

    # Store attention proxy
    paper._attention_score = round(attention_proxy, 2)

    return paper


# ============================================================
# QUALITY FILTERS
# ============================================================

def _filter_models(models: list[Paper]) -> list[Paper]:
    """
    Filter out low-quality or irrelevant models.
    Keeps models that are likely to be interesting to users.
    """
    filtered = []
    for model in models:
        # Skip models with very low engagement
        # Parse downloads from description
        try:
            desc = model.abstract
            dl_str = desc.split("Downloads: ")[1].split(".")[0].replace(",", "")
            likes_str = desc.split("Likes: ")[1].split(".")[0].replace(",", "")
            downloads = int(dl_str)
            likes = int(likes_str)
        except Exception:
            downloads = 0
            likes = 0

        # Apply minimum thresholds
        if downloads >= MIN_DOWNLOADS or likes >= MIN_LIKES:
            filtered.append(model)

    return filtered


# ============================================================
# HELPERS
# ============================================================

def _detect_topic_from_tags(tags: list[str], title: str) -> str:
    """Detect topic from HuggingFace model tags."""
    tags_lower = [t.lower() for t in tags]
    title_lower = title.lower()
    combined = " ".join(tags_lower) + " " + title_lower

    if any(t in combined for t in ["text-generation", "llm", "chat", "gpt", "llama", "mistral"]):
        return "LLMs"
    if any(t in combined for t in ["image-generation", "diffusion", "text-to-image", "stable-diffusion"]):
        return "Diffusion Models"
    if any(t in combined for t in ["multimodal", "vision-language", "image-to-text", "vqa"]):
        return "Multimodal"
    if any(t in combined for t in ["text2text", "translation", "summarization", "nlp"]):
        return "NLP"
    if any(t in combined for t in ["reinforcement", "rl", "reward"]):
        return "RL / Agents"

    return "Model Efficiency"


def _parse_hf_date(date_str: str) -> datetime:
    """Parse HuggingFace date format."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        # HF format: "2025-03-22T10:00:00.000Z"
        clean = date_str.replace("Z", "+00:00")
        if "." in clean:
            clean = clean.split(".")[0] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


# ============================================================
# TEST
# Command: python scrapers/huggingface.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing HuggingFace Scraper")
    print(f"{'='*55}\n")

    print(f"Fetching models (max 3 per category)...")
    models = await fetch_new_models(max_per_category=3)

    if models:
        print(f"\n✅ Got {len(models)} models!\n")
        print("Sample models:")
        for m in models[:5]:
            print(f"\n  ID     : {m.id}")
            print(f"  Title  : {m.title[:60]}")
            print(f"  Topic  : {m.topic}")
            print(f"  Type   : {m.paper_type}")
            print(f"  URL    : {m.url}")
            print(f"  Score  : {getattr(m, '_attention_score', 0)}")
    else:
        print("❌ No models fetched — check internet or MIN_LIKES/MIN_DOWNLOADS thresholds")

    print(f"\n{'='*55}")
    print(f"  HuggingFace scraper test done!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())

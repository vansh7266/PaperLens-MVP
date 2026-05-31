# tests/test_radar_processor.py
#
# Unit tests for radar/pipeline/processor.py
# All tests are purely in-memory — no DB, no LLM, no network calls.
# Deduplication tests mock the DB calls.

import pytest
from unittest.mock import AsyncMock, patch

from radar.pipeline.processor import Processor


@pytest.fixture
def processor():
    return Processor()


# ---------------------------------------------------------------------------
# Topic classification
# ---------------------------------------------------------------------------

class TestClassifyTopic:

    def test_llm_paper_classified_as_llms(self, processor):
        topic = processor.classify_topic(
            "Large Language Model reasoning with chain-of-thought",
            "We study instruction tuning and in-context learning for GPT-style models."
        )
        assert topic == "LLMs"

    def test_vision_paper_classified_as_cv(self, processor):
        topic = processor.classify_topic(
            "DiffusionDet: Object detection via diffusion",
            "We propose a convolutional image classification approach using ViT architecture."
        )
        # "diffusion" matches "Diffusion Models" topic in TOPIC_MAP
        assert topic in ("Diffusion Models", "Computer Vision")

    def test_rl_paper(self, processor):
        topic = processor.classify_topic(
            "PPO-based reinforcement learning for multi-agent systems",
            "We study policy gradient and actor-critic methods with reward shaping."
        )
        assert topic == "RL / Agents"

    def test_unknown_returns_other(self, processor):
        topic = processor.classify_topic(
            "Quantum computing entanglement protocols",
            "This paper has nothing to do with AI or ML whatsoever."
        )
        assert topic == "Other"

    def test_title_weighted_higher_than_content(self, processor):
        # Title is all LLM keywords — should dominate over generic content
        topic = processor.classify_topic(
            "GPT large language model transformer prompt",
            "Some unrelated content about physics and mathematics."
        )
        assert topic == "LLMs"

    def test_multimodal_takes_priority(self, processor):
        topic = processor.classify_topic(
            "Vision-Language Models for VQA",
            "We introduce a multimodal clip-based visual question answering system."
        )
        assert topic == "Multimodal"


# ---------------------------------------------------------------------------
# Difficulty detection
# ---------------------------------------------------------------------------

class TestDetectDifficulty:

    def test_survey_paper_is_easy(self, processor):
        diff = processor.detect_difficulty(
            "Introduction to Reinforcement Learning: A Survey",
            "An introductory survey and tutorial for beginners.",
            "paper"
        )
        assert diff == "Easy"

    def test_math_heavy_paper_is_advanced(self, processor):
        diff = processor.detect_difficulty(
            "Convergence Proof for Stochastic Gradient Methods",
            "We provide theoretical convergence proofs and asymptotic bounds. "
            "Using variational inference, Bayesian posteriors and gradient analysis.",
            "paper"
        )
        assert diff == "Advanced"

    def test_normal_paper_is_intermediate(self, processor):
        diff = processor.detect_difficulty(
            "A New Training Approach for Transformers",
            "We propose an efficient fine-tuning method that achieves strong performance.",
            "paper"
        )
        assert diff == "Intermediate"

    def test_blog_post_always_intermediate(self, processor):
        # Non-papers always return Intermediate regardless of content
        diff = processor.detect_difficulty(
            "Introduction to Claude 3",
            "An easy tutorial survey overview for beginners.",
            "blog_post"
        )
        assert diff == "Intermediate"

    def test_model_always_intermediate(self, processor):
        diff = processor.detect_difficulty(
            "Introduction to llama model survey",
            "Tutorial guide beginners.",
            "model"
        )
        assert diff == "Intermediate"


# ---------------------------------------------------------------------------
# Key tags extraction
# ---------------------------------------------------------------------------

class TestExtractKeyTags:

    def test_extracts_matching_keywords(self, processor):
        tags = processor.extract_key_tags(
            "State-of-the-Art benchmark for reasoning",
            "We propose a new open-source architecture with efficient training."
        )
        assert "benchmark" in tags or "state-of-the-art" in tags
        assert "open-source" in tags or "efficient" in tags

    def test_returns_at_most_6_tags(self, processor):
        # Even with many keywords, cap at 6
        tags = processor.extract_key_tags(
            "benchmark state-of-the-art efficient reasoning agent multimodal open-source dataset",
            "architecture breakthrough novel new model instruction alignment safety scalable"
        )
        assert len(tags) <= 6

    def test_empty_content_returns_empty(self, processor):
        tags = processor.extract_key_tags("", "")
        assert tags == []

    def test_no_matches_returns_empty(self, processor):
        tags = processor.extract_key_tags(
            "Quantum physics entanglement",
            "This is about chemistry and biology."
        )
        assert tags == []


# ---------------------------------------------------------------------------
# Attention score
# ---------------------------------------------------------------------------

class TestAttentionScore:

    def test_fresh_arxiv_high_impact_scores_high(self, processor):
        import datetime
        published = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        ).isoformat()

        score = processor.calculate_attention_score(
            source_name  = "arXiv",
            published_at = published,
            title        = "State-of-the-Art Benchmark for Reasoning with New Architecture",
            full_content = "We introduce a novel open-source model that outperforms existing benchmarks.",
            metadata_json= None,
        )
        assert score > 70, f"Expected high score, got {score}"

    def test_old_low_quality_scores_low(self, processor):
        import datetime
        published = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)
        ).isoformat()

        score = processor.calculate_attention_score(
            source_name  = "HuggingFace",
            published_at = published,
            title        = "My Fine-tuned Model",
            full_content = "A personal fine-tune with no special properties.",
            metadata_json= None,
        )
        assert score < 25, f"Expected low score, got {score}"

    def test_score_capped_at_100(self, processor):
        import datetime
        published = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
        ).isoformat()

        score = processor.calculate_attention_score(
            source_name  = "Anthropic",
            published_at = published,
            title        = " ".join(["benchmark state-of-the-art sota outperforms efficient"] * 5),
            full_content = " ".join(["we introduce open-source agent multimodal reasoning"] * 5),
            metadata_json= {"citation_count": 10000, "likes": 5000, "downloads": 100000},
        )
        assert score <= 100.0

    def test_score_non_negative(self, processor):
        score = processor.calculate_attention_score(
            source_name  = "unknown",
            published_at = None,
            title        = "",
            full_content = "",
            metadata_json= None,
        )
        assert score >= 0.0

    def test_freshness_difference(self, processor):
        import datetime
        recent = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat()
        old = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
        ).isoformat()

        score_recent = processor.calculate_attention_score(
            "arXiv", recent, "Same title", "Same content", None
        )
        score_old = processor.calculate_attention_score(
            "arXiv", old, "Same title", "Same content", None
        )
        assert score_recent > score_old


# ---------------------------------------------------------------------------
# Signal label
# ---------------------------------------------------------------------------

class TestSignalLabel:

    def test_high_score_is_high_signal(self, processor):
        label = processor.assign_signal_label(85.0, "paper")
        assert label == "High Signal"

    def test_medium_score_paper_is_worth_peeling(self, processor):
        label = processor.assign_signal_label(65.0, "paper")
        assert label == "Worth Peeling"

    def test_medium_score_blog_is_worth_watching(self, processor):
        # blogs can't be "Worth Peeling"
        label = processor.assign_signal_label(65.0, "blog_post")
        assert label == "Worth Watching"

    def test_low_score_is_quick_skim(self, processor):
        label = processor.assign_signal_label(20.0, "paper")
        assert label == "Quick Skim"

    def test_model_above_watching_threshold(self, processor):
        label = processor.assign_signal_label(50.0, "model")
        assert label == "Worth Watching"


# ---------------------------------------------------------------------------
# Full process_items pipeline (with mocked DB)
# ---------------------------------------------------------------------------

class TestProcessItems:

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, processor):
        result = await processor.process_items([])
        assert result == []

    @pytest.mark.asyncio
    async def test_item_missing_source_url_is_skipped(self, processor):
        with patch.object(processor, "_get_existing_urls", new=AsyncMock(return_value=set())):
            with patch.object(processor, "_get_existing_arxiv_ids", new=AsyncMock(return_value=set())):
                result = await processor.process_items([
                    {"title": "No URL item", "full_content": "test", "content_type": "paper"}
                ])
        assert result == []

    @pytest.mark.asyncio
    async def test_duplicate_url_skipped(self, processor):
        items = [{
            "title": "Test paper",
            "source_url": "https://arxiv.org/abs/2301.00001",
            "source_name": "arXiv",
            "content_type": "paper",
            "arxiv_id": "2301.00001",
            "authors": [],
            "full_content": "Test abstract",
            "published_at": None,
            "metadata_json": {},
        }]
        with patch.object(
            processor, "_get_existing_urls",
            new=AsyncMock(return_value={"https://arxiv.org/abs/2301.00001"})
        ):
            with patch.object(processor, "_get_existing_arxiv_ids", new=AsyncMock(return_value=set())):
                result = await processor.process_items(items)
        assert result == []

    @pytest.mark.asyncio
    async def test_new_item_processed_correctly(self, processor):
        import datetime
        pub = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)
        ).isoformat()

        items = [{
            "title": "Efficient Large Language Model reasoning with chain-of-thought prompting",
            "source_url": "https://arxiv.org/abs/2301.99999",
            "source_name": "arXiv",
            "content_type": "paper",
            "arxiv_id": "2301.99999",
            "authors": ["Alice", "Bob"],
            "full_content": (
                "We introduce a new benchmark for instruction tuning with transformer models. "
                "Our open-source approach outperforms state-of-the-art baselines significantly."
            ),
            "published_at": pub,
            "metadata_json": {"category": "cs.AI"},
        }]

        with patch.object(processor, "_get_existing_urls", new=AsyncMock(return_value=set())):
            with patch.object(processor, "_get_existing_arxiv_ids", new=AsyncMock(return_value=set())):
                result = await processor.process_items(items)

        assert len(result) == 1
        item = result[0]

        # Topic: strong LLM signals
        assert item["topic"] in ("LLMs", "NLP")

        # Difficulty: no strong advanced keywords → Intermediate
        assert item["difficulty"] == "Intermediate"

        # Key tags should include some impact keywords
        assert len(item["key_tags"]) > 0

        # Score should be meaningful (recent + good source + impact keywords)
        assert item["attention_score"] > 30

        # Signal label should be assigned
        assert item["signal_label"] in (
            "High Signal", "Worth Peeling", "Worth Watching", "Quick Skim"
        )

        # Papers can be peeled
        assert item["has_peeler"] is True

        # Summarizer fields start as None/False
        assert item["summary"] is None
        assert item["why_it_matters"] is None
        assert item["is_summarized"] is False

    @pytest.mark.asyncio
    async def test_blog_post_has_no_peeler(self, processor):
        items = [{
            "title": "Anthropic Announces Claude 4",
            "source_url": "https://anthropic.com/news/claude-4",
            "source_name": "Anthropic",
            "content_type": "blog_post",
            "arxiv_id": None,
            "authors": [],
            "full_content": "We introduce Claude 4, our newest model with new architecture.",
            "published_at": None,
            "metadata_json": {},
        }]

        with patch.object(processor, "_get_existing_urls", new=AsyncMock(return_value=set())):
            with patch.object(processor, "_get_existing_arxiv_ids", new=AsyncMock(return_value=set())):
                result = await processor.process_items(items)

        assert len(result) == 1
        assert result[0]["has_peeler"] is False
        assert result[0]["difficulty"] == "Intermediate"   # non-paper always Intermediate

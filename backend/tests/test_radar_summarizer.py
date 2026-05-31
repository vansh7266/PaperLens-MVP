# tests/test_radar_summarizer.py
#
# Unit tests for radar/pipeline/summarizer.py
# All LLM and DB calls are mocked — no API keys needed.

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from radar.pipeline.summarizer import Summarizer


@pytest.fixture
def summarizer():
    # Mock the LLM so tests don't need OPENAI_API_KEY or GROQ_API_KEY
    with patch("radar.pipeline.summarizer.get_radar_llm") as mock_factory:
        mock_llm = AsyncMock()
        mock_factory.return_value = mock_llm
        s = Summarizer()
        s.llm = mock_llm
        yield s


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:

    def test_includes_title(self, summarizer):
        prompt = summarizer._build_prompt(
            "Attention Is All You Need", "Abstract text here", "paper"
        )
        assert "Attention Is All You Need" in prompt

    def test_includes_content_type(self, summarizer):
        prompt = summarizer._build_prompt("Title", "Content", "blog_post")
        assert "blog_post" in prompt

    def test_truncates_long_content(self, summarizer):
        from config import RADAR_MAX_CONTENT_CHARS
        long_content = "x" * (RADAR_MAX_CONTENT_CHARS + 500)
        prompt = summarizer._build_prompt("Title", long_content, "paper")
        assert "[Content truncated]" in prompt

    def test_short_content_not_truncated(self, summarizer):
        short_content = "Short abstract."
        prompt = summarizer._build_prompt("Title", short_content, "paper")
        assert "[Content truncated]" not in prompt


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_parses_well_formed_response(self, summarizer):
        text = (
            "SUMMARY: This paper introduces a new approach to reasoning.\n"
            "WHY_IT_MATTERS: Engineers can use this to build better agents."
        )
        summary, why = summarizer._parse_response(text)
        assert "new approach to reasoning" in summary
        assert "Engineers" in why

    def test_handles_missing_why_it_matters(self, summarizer):
        text = "SUMMARY: Just a summary here, no why."
        summary, why = summarizer._parse_response(text)
        assert "Just a summary" in summary
        assert why == "" or why is not None  # empty is fine, but no crash

    def test_fallback_on_unformatted_response(self, summarizer):
        text = "Some unformatted response from LLM that doesn't follow instructions."
        summary, why = summarizer._parse_response(text)
        # Should use full text as fallback summary
        assert len(summary) > 0
        assert "Some unformatted" in summary

    def test_empty_response_returns_empty_strings(self, summarizer):
        summary, why = summarizer._parse_response("")
        assert summary == ""
        assert why == ""

    def test_multiline_summary(self, summarizer):
        text = (
            "SUMMARY: First line of summary.\n"
            "Still part of summary.\n"
            "WHY_IT_MATTERS: This changes how we build systems."
        )
        summary, why = summarizer._parse_response(text)
        assert "First line" in summary
        assert "changes how" in why


# ---------------------------------------------------------------------------
# _summarize_one
# ---------------------------------------------------------------------------

class TestSummarizeOne:

    @pytest.mark.asyncio
    async def test_returns_parsed_tuple_on_success(self, summarizer):
        summarizer.llm.generate = AsyncMock(return_value=(
            "SUMMARY: A great paper about transformers.\n"
            "WHY_IT_MATTERS: It enables faster training."
        ))
        result = await summarizer._summarize_one("item-1", "Transformers", "Abstract", "paper")
        assert result is not None
        summary, why = result
        assert "great paper" in summary
        assert "faster training" in why

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_returns_empty(self, summarizer):
        summarizer.llm.generate = AsyncMock(return_value="")
        result = await summarizer._summarize_one("item-1", "Title", "Content", "paper")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_exception(self, summarizer):
        summarizer.llm.generate = AsyncMock(side_effect=RuntimeError("LLM error"))
        result = await summarizer._summarize_one("item-1", "Title", "Content", "paper")
        assert result is None


# ---------------------------------------------------------------------------
# summarize_batch
# ---------------------------------------------------------------------------

class TestSummarizeBatch:

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, summarizer):
        result = await summarizer.summarize_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_already_summarized_items_pass_through(self, summarizer):
        items = [
            {"id": "1", "title": "T", "full_content": "C",
             "content_type": "paper", "is_summarized": True,
             "summary": "Existing summary", "why_it_matters": "Existing why"},
        ]
        result = await summarizer.summarize_batch(items)
        assert len(result) == 1
        assert result[0]["summary"] == "Existing summary"
        # LLM should NOT be called for already-summarized items
        summarizer.llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_item_missing_id_is_returned_unchanged(self, summarizer):
        items = [
            {"title": "No ID item", "full_content": "Content",
             "content_type": "paper", "is_summarized": False},
        ]
        # Should return item unchanged (no id = can't save to DB)
        summarizer.llm.generate = AsyncMock(return_value="SUMMARY: Test\nWHY_IT_MATTERS: Because.")
        result = await summarizer.summarize_batch(items)
        assert len(result) == 1
        # is_summarized stays False because no id
        assert result[0].get("is_summarized", False) is False

    @pytest.mark.asyncio
    async def test_successful_summarization_updates_item(self, summarizer):
        items = [{
            "id": "item-uuid-1",
            "title": "A new LLM paper",
            "full_content": "We propose a new transformer architecture.",
            "content_type": "paper",
            "is_summarized": False,
        }]

        summarizer.llm.generate = AsyncMock(return_value=(
            "SUMMARY: Proposes a new transformer.\n"
            "WHY_IT_MATTERS: Faster inference."
        ))

        with patch.object(summarizer, "_save_summary", new=AsyncMock(return_value=True)):
            result = await summarizer.summarize_batch(items)

        assert len(result) == 1
        assert result[0]["is_summarized"] is True
        assert "transformer" in result[0]["summary"]
        assert "Faster" in result[0]["why_it_matters"]

    @pytest.mark.asyncio
    async def test_llm_failure_leaves_item_unsummarized(self, summarizer):
        items = [{
            "id": "item-uuid-2",
            "title": "Title",
            "full_content": "Content",
            "content_type": "paper",
            "is_summarized": False,
        }]
        summarizer.llm.generate = AsyncMock(return_value="")
        result = await summarizer.summarize_batch(items)
        assert len(result) == 1
        assert result[0].get("is_summarized", False) is False

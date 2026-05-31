# tests/test_radar_routes.py
#
# Integration tests for Radar API routes.
# Uses FastAPI TestClient with mocked DB and auth dependencies.

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from main import app
from routes.auth import get_current_user


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MOCK_USER = {"sub": "test-user-uuid-1234", "email": "test@example.com"}
MOCK_PRO_PLAN  = "pro"
MOCK_FREE_PLAN = "free"

MOCK_FEED_ITEM = {
    "id":              "item-uuid-abc",
    "title":           "Attention Is All You Need for Reasoning",
    "summary":         "A transformer paper about reasoning.",
    "why_it_matters":  "Changes how we build LLMs.",
    "source_url":      "https://arxiv.org/abs/2301.00001",
    "source_name":     "arXiv",
    "content_type":    "paper",
    "authors":         ["Vaswani et al."],
    "published_at":    "2024-01-15T10:00:00",
    "fetched_at":      "2024-01-15T10:30:00",
    "topic":           "LLMs",
    "difficulty":      "Intermediate",
    "attention_score": 82.5,
    "signal_label":    "High Signal",
    "key_tags":        ["benchmark", "reasoning"],
    "has_peeler":      True,
    "is_summarized":   True,
}

MOCK_BRIEF = {
    "papers":          [MOCK_FEED_ITEM],
    "models":          [],
    "company_updates": [],
    "total":           1,
    "generated_at":    "2024-01-15T08:00:00+00:00",
    "date_label":      "Today, Jan 15",
}


@pytest.fixture
def client():
    """TestClient with auth dependency overridden."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/radar/today
# ---------------------------------------------------------------------------

class TestTodayBrief:

    def test_returns_brief_structure(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar.build_today_brief", new=AsyncMock(return_value=MOCK_BRIEF)):
                resp = client.get("/api/radar/today")

        assert resp.status_code == 200
        data = resp.json()
        assert "papers" in data
        assert "models" in data
        assert "company_updates" in data
        assert "total" in data
        assert "date_label" in data
        assert data["plan"] == MOCK_PRO_PLAN

    def test_brief_papers_have_required_fields(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar.build_today_brief", new=AsyncMock(return_value=MOCK_BRIEF)):
                resp = client.get("/api/radar/today")

        data = resp.json()
        if data["papers"]:
            paper = data["papers"][0]
            assert "id" in paper
            assert "title" in paper
            assert "signal_label" in paper
            assert "has_peeler" in paper

    def test_public_access_without_auth(self):
        # Radar read endpoints are public (optional auth) — should return 200, not 401
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value="free")):
            with patch("radar.routes.radar.build_today_brief", new=AsyncMock(return_value={
                "papers": [], "models": [], "company_updates": [],
                "total": 0, "generated_at": "2026-01-01T00:00:00Z",
                "date_label": "Today", "plan": "free"
            })):
                test_app_no_auth = TestClient(app, raise_server_exceptions=False)
                resp = test_app_no_auth.get("/api/radar/today")
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/radar/papers
# ---------------------------------------------------------------------------

class TestPapersFeed:

    def test_returns_feed_structure(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar._get_feed", new=AsyncMock(return_value=[MOCK_FEED_ITEM])):
                resp = client.get("/api/radar/papers")

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data
        assert "has_more" in data
        assert data["plan"] == MOCK_PRO_PLAN

    def test_invalid_sort_returns_400(self, client):
        resp = client.get("/api/radar/papers?sort=invalid")
        assert resp.status_code == 400

    def test_valid_sort_newest(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar._get_feed", new=AsyncMock(return_value=[])):
                resp = client.get("/api/radar/papers?sort=newest")
        assert resp.status_code == 200

    def test_pagination_offset(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar._get_feed", new=AsyncMock(return_value=[])):
                resp = client.get("/api/radar/papers?offset=50")
        assert resp.status_code == 200
        assert resp.json()["offset"] == 50

    def test_topic_filter_passed(self, client):
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            mock_feed = AsyncMock(return_value=[MOCK_FEED_ITEM])
            with patch("radar.routes.radar._get_feed", new=mock_feed):
                resp = client.get("/api/radar/papers?topic=LLMs")
        assert resp.status_code == 200
        # Verify topic was passed to _get_feed
        mock_feed.assert_called_once_with("paper", MOCK_PRO_PLAN, "LLMs", "attention", 0)


# ---------------------------------------------------------------------------
# GET /api/radar/models
# ---------------------------------------------------------------------------

class TestModelsFeed:

    def test_returns_200_with_items(self, client):
        model_item = {**MOCK_FEED_ITEM, "content_type": "model", "has_peeler": False}
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar._get_feed", new=AsyncMock(return_value=[model_item])):
                resp = client.get("/api/radar/models")

        assert resp.status_code == 200
        assert resp.json()["count"] == 1


# ---------------------------------------------------------------------------
# GET /api/radar/companies
# ---------------------------------------------------------------------------

class TestCompaniesFeed:

    def test_returns_200(self, client):
        blog_item = {**MOCK_FEED_ITEM, "content_type": "blog_post", "has_peeler": False}
        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar._get_feed", new=AsyncMock(return_value=[blog_item])):
                resp = client.get("/api/radar/companies")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/radar/stats
# ---------------------------------------------------------------------------

class TestRadarStats:

    def test_returns_stats_structure(self, client):
        mock_rows = [
            {"content_type": "paper",    "topic": "LLMs",         "signal_label": "High Signal"},
            {"content_type": "paper",    "topic": "LLMs",         "signal_label": "Worth Peeling"},
            {"content_type": "model",    "topic": "Other",        "signal_label": "Worth Watching"},
            {"content_type": "blog_post","topic": "AI Safety",    "signal_label": "Quick Skim"},
        ]

        # Stats query chain for pro: .select().eq("is_summarized").gte().limit()
        # Build a flexible chain that returns execute AsyncMock at any depth
        mock_execute = AsyncMock(return_value=MagicMock(data=mock_rows))

        def make_chain():
            chain = MagicMock()
            chain.execute = mock_execute
            chain.eq  = lambda *a, **kw: make_chain()
            chain.gte = lambda *a, **kw: make_chain()
            chain.limit = lambda *a, **kw: make_chain()
            return chain

        mock_table = MagicMock()
        mock_table.select = lambda *a, **kw: make_chain()

        mock_db = MagicMock()
        mock_db.table = lambda name: mock_table

        with patch("radar.routes.radar._get_user_plan", new=AsyncMock(return_value=MOCK_PRO_PLAN)):
            with patch("radar.routes.radar.get_service_client", new=AsyncMock(return_value=mock_db)):
                resp = client.get("/api/radar/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert "scanned_today" in data
        assert "high_signal" in data
        assert "by_type" in data
        assert "by_topic" in data

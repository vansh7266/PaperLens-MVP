import asyncio

from fastapi.testclient import TestClient

from main import app
from routes import peeler
from core.peeler_repository import MemoryPeelerRepository
from core.peeler_service import PeelerService

from test_peeler_core import sample_paper, sample_peel


async def fake_user():
    return {"sub": "route-user", "email": "route@paperlens.local"}


def install_test_peeler(repo: MemoryPeelerRepository, service: PeelerService):
    peeler.repository = repo
    peeler.service = service
    app.dependency_overrides[peeler.get_current_user] = fake_user


def clear_test_peeler():
    app.dependency_overrides.pop(peeler.get_current_user, None)


def test_cached_job_endpoint_does_not_consume_peel_credit():
    repo = MemoryPeelerRepository()
    service = PeelerService(repo)
    paper = sample_paper()
    peel = sample_peel()

    async def seed():
        await repo.save_paper(paper)
        await repo.save_global_peel(peel)
        await repo.set_usage("route-user", new_peels_used=1, chat_messages_used=0)

    asyncio.run(seed())
    install_test_peeler(repo, service)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/peeler/jobs",
                json={"paper": paper.model_dump(mode="json")},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "completed"
            assert body["completed_from_cache"] is True
            assert body["consumed_credit"] is False

            usage = client.get("/api/usage").json()
            assert usage["new_peels_used"] == 1
            assert usage["cached_peels_cost_credits"] is False
    finally:
        clear_test_peeler()


def test_chat_stream_endpoint_persists_messages_and_consumes_chat_credit():
    repo = MemoryPeelerRepository()
    service = PeelerService(
        repo,
        chat_generator=lambda _thread_id, question: f"Grounded answer for: {question}",
    )
    paper = sample_paper()
    peel = sample_peel()

    async def seed():
        await repo.save_paper(paper)
        await repo.save_global_peel(peel)
        thread = await repo.create_thread("route-user", paper.canonical_id, peel.paper_id)
        return thread.thread_id

    thread_id = asyncio.run(seed())
    install_test_peeler(repo, service)
    try:
        with TestClient(app) as client:
            with client.stream(
                "POST",
                f"/api/peeler/threads/{thread_id}/chat/stream",
                json={"question": "How does self-attention work?"},
            ) as response:
                assert response.status_code == 200
                stream_body = "".join(response.iter_text())
                assert "Grounded" in stream_body
                assert "answer" in stream_body
                assert "\"type\": \"done\"" in stream_body

            usage = client.get("/api/usage").json()
            assert usage["chat_messages_used"] == 1

            thread = client.get(f"/api/peeler/threads/{thread_id}").json()
            assert [message["role"] for message in thread["messages"][-2:]] == [
                "user",
                "assistant",
            ]
    finally:
        clear_test_peeler()

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.peeler_models import (
    ChatMessage,
    PaperChunk,
    PaperRecord,
    PeelJob,
    PeelOutput,
    ThreadRecord,
    UserUsage,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryPeelerRepository:
    """
    Runtime repository used for local development and tests.

    The service depends on this small async interface so a Supabase-backed
    implementation can replace it without changing route or UI behavior.
    """

    def __init__(self) -> None:
        self.papers: dict[str, PaperRecord] = {}
        self.chunks: dict[str, list[PaperChunk]] = {}
        self.global_peels: dict[str, PeelOutput] = {}
        self.jobs: dict[str, PeelJob] = {}
        self.threads: dict[str, ThreadRecord] = {}
        self.thread_messages: dict[str, list[ChatMessage]] = {}
        self.usage: dict[str, UserUsage] = {}

    async def save_paper(self, paper: PaperRecord) -> PaperRecord:
        self.papers[paper.canonical_id] = paper
        return paper

    async def get_paper(self, paper_id: str) -> PaperRecord | None:
        return self.papers.get(paper_id)

    async def save_chunks(self, paper_id: str, chunks: list[PaperChunk]) -> None:
        self.chunks[paper_id] = chunks

    async def get_chunks(self, paper_id: str, limit: int = 8) -> list[PaperChunk]:
        return self.chunks.get(paper_id, [])[:limit]

    async def save_global_peel(self, peel: PeelOutput) -> PeelOutput:
        self.global_peels[peel.paper_id] = peel
        return peel

    async def get_global_peel(self, paper_id: str) -> PeelOutput | None:
        return self.global_peels.get(paper_id)

    async def create_job(self, job: PeelJob) -> PeelJob:
        self.jobs[job.job_id] = job
        return job

    async def update_job(self, job_id: str, **updates) -> PeelJob:
        job = self.jobs[job_id]
        data = job.model_dump()
        data.update(updates)
        data["updated_at"] = _now()
        updated = PeelJob.model_validate(data)
        self.jobs[job_id] = updated
        return updated

    async def get_job(self, job_id: str) -> PeelJob | None:
        return self.jobs.get(job_id)

    async def create_thread(self, user_id: str, paper_id: str, peel_output_id: str, title: str = "") -> ThreadRecord:
        thread = ThreadRecord(
            user_id=user_id,
            paper_id=paper_id,
            peel_output_id=peel_output_id,
            title=title,
        )
        self.threads[thread.thread_id] = thread
        self.thread_messages[thread.thread_id] = []
        return thread

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        return self.threads.get(thread_id)

    async def list_threads(self, user_id: str) -> list[ThreadRecord]:
        return [
            thread for thread in self.threads.values()
            if thread.user_id == user_id
        ]

    async def add_message(self, thread_id: str, message: ChatMessage) -> None:
        if thread_id not in self.thread_messages:
            self.thread_messages[thread_id] = []
        payload = message.model_dump()
        payload["created_at"] = payload.get("created_at") or _now()
        self.thread_messages[thread_id].append(ChatMessage.model_validate(payload))

    async def get_thread_messages(self, thread_id: str, limit: int = 30) -> list[ChatMessage]:
        return self.thread_messages.get(thread_id, [])[-limit:]

    async def get_usage(self, user_id: str) -> UserUsage:
        if user_id not in self.usage:
            self.usage[user_id] = UserUsage(user_id=user_id)
        return self.usage[user_id]

    async def set_usage(
        self,
        user_id: str,
        *,
        new_peels_used: int | None = None,
        chat_messages_used: int | None = None,
        failed_jobs_count: int | None = None,
        plan: str | None = None,
    ) -> UserUsage:
        current = await self.get_usage(user_id)
        payload = current.model_dump()
        if new_peels_used is not None:
            payload["new_peels_used"] = new_peels_used
        if chat_messages_used is not None:
            payload["chat_messages_used"] = chat_messages_used
        if failed_jobs_count is not None:
            payload["failed_jobs_count"] = failed_jobs_count
        if plan is not None:
            payload["plan"] = plan
        self.usage[user_id] = UserUsage.model_validate(payload)
        return self.usage[user_id]

    async def increment_new_peels(self, user_id: str) -> UserUsage:
        usage = await self.get_usage(user_id)
        return await self.set_usage(user_id, new_peels_used=usage.new_peels_used + 1)

    async def increment_chat_messages(self, user_id: str) -> UserUsage:
        usage = await self.get_usage(user_id)
        return await self.set_usage(user_id, chat_messages_used=usage.chat_messages_used + 1)

    async def increment_failed_jobs(self, user_id: str) -> UserUsage:
        usage = await self.get_usage(user_id)
        return await self.set_usage(user_id, failed_jobs_count=usage.failed_jobs_count + 1)


def _paper_to_row(paper: PaperRecord) -> dict[str, Any]:
    payload = paper.model_dump(mode="json")
    payload["paper_id"] = paper.canonical_id
    payload["updated_at"] = _now()
    return payload


def _row_to_paper(row: dict[str, Any]) -> PaperRecord:
    payload = {
        "canonical_id": row.get("canonical_id") or row.get("paper_id"),
        "source_type": row.get("source_type") or row.get("source") or "feed",
        "title": row.get("title") or "Untitled paper",
        "authors": row.get("authors") or [],
        "abstract": row.get("abstract") or "",
        "source_url": row.get("source_url") or row.get("url"),
        "pdf_url": row.get("pdf_url"),
        "arxiv_id": row.get("arxiv_id"),
        "doi": row.get("doi"),
        "published_at": row.get("published_at"),
        "topic": row.get("topic") or "General_AI",
        "difficulty": row.get("difficulty") or "Intermediate",
        "confidence": row.get("confidence") or "medium",
        "extraction_quality": row.get("extraction_quality"),
        "is_private": row.get("is_private") or False,
    }
    return PaperRecord.model_validate(payload)


class SupabasePeelerRepository(MemoryPeelerRepository):
    """
    Supabase-backed repository for launch deployments.

    It intentionally preserves the same async interface as the local memory
    repository so tests and routes do not care which storage backend is active.
    """

    def _db(self):
        from core.database import get_service_client

        return get_service_client()

    async def save_paper(self, paper: PaperRecord) -> PaperRecord:
        self._db().table("papers").upsert(
            _paper_to_row(paper),
            on_conflict="paper_id",
        ).execute()
        return paper

    async def get_paper(self, paper_id: str) -> PaperRecord | None:
        try:
            result = self._db().table("papers").select("*").eq(
                "paper_id", paper_id
            ).limit(1).execute()
            if not result.data:
                return None
            return _row_to_paper(result.data[0])
        except Exception:
            return None

    async def save_chunks(self, paper_id: str, chunks: list[PaperChunk]) -> None:
        db = self._db()
        db.table("paper_chunks").delete().eq("paper_id", paper_id).execute()
        if not chunks:
            return
        db.table("paper_chunks").insert([
            chunk.model_dump(mode="json") for chunk in chunks
        ]).execute()

    async def get_chunks(self, paper_id: str, limit: int = 8) -> list[PaperChunk]:
        try:
            result = self._db().table("paper_chunks").select("*").eq(
                "paper_id", paper_id
            ).order("page_start").limit(limit).execute()
            return [PaperChunk.model_validate(row) for row in (result.data or [])]
        except Exception:
            return []

    async def save_global_peel(self, peel: PeelOutput) -> PeelOutput:
        db = self._db()
        db.table("peel_outputs").upsert(
            {
                "paper_id": peel.paper_id,
                "schema_version": peel.schema_version,
                "sections_json": {
                    key: value.model_dump(mode="json")
                    for key, value in peel.sections.items()
                },
                "architecture_json": peel.architecture.model_dump(mode="json"),
                "math_peel_json": [item.model_dump(mode="json") for item in peel.math_peel],
                "related_papers_json": [item.model_dump(mode="json") for item in peel.related_papers],
                "suggested_questions": peel.suggested_questions,
                "model_used": peel.model_used,
                "created_at": peel.created_at,
                "completed_from_cache": peel.completed_from_cache,
            },
            on_conflict="paper_id",
        ).execute()
        db.table("papers").update({"has_peeler": True}).eq("paper_id", peel.paper_id).execute()
        return peel

    async def get_global_peel(self, paper_id: str) -> PeelOutput | None:
        try:
            result = self._db().table("peel_outputs").select("*").eq(
                "paper_id", paper_id
            ).limit(1).execute()
            if not result.data:
                return None
            row = result.data[0]
            return PeelOutput.model_validate({
                "paper_id": row["paper_id"],
                "schema_version": row.get("schema_version") or "1.0",
                "sections": row.get("sections_json") or {},
                "architecture": row.get("architecture_json") or {},
                "math_peel": row.get("math_peel_json") or [],
                "related_papers": row.get("related_papers_json") or [],
                "suggested_questions": row.get("suggested_questions") or [],
                "created_at": row.get("created_at") or _now(),
                "model_used": row.get("model_used") or "unknown",
                "completed_from_cache": row.get("completed_from_cache") or False,
            })
        except Exception:
            return None

    async def create_job(self, job: PeelJob) -> PeelJob:
        self._db().table("peel_jobs").insert(job.model_dump(mode="json")).execute()
        return job

    async def update_job(self, job_id: str, **updates) -> PeelJob:
        updates["updated_at"] = _now()
        self._db().table("peel_jobs").update(updates).eq("job_id", job_id).execute()
        job = await self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return job

    async def get_job(self, job_id: str) -> PeelJob | None:
        try:
            result = self._db().table("peel_jobs").select("*").eq(
                "job_id", job_id
            ).limit(1).execute()
            return PeelJob.model_validate(result.data[0]) if result.data else None
        except Exception:
            return None

    async def create_thread(self, user_id: str, paper_id: str, peel_output_id: str, title: str = "") -> ThreadRecord:
        thread = ThreadRecord(
            user_id=user_id,
            paper_id=paper_id,
            peel_output_id=peel_output_id,
            title=title,
        )
        self._db().table("user_threads").insert(thread.model_dump(mode="json")).execute()
        return thread

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        try:
            result = self._db().table("user_threads").select("*").eq(
                "thread_id", thread_id
            ).limit(1).execute()
            return ThreadRecord.model_validate(result.data[0]) if result.data else None
        except Exception:
            return None

    async def list_threads(self, user_id: str) -> list[ThreadRecord]:
        try:
            result = self._db().table("user_threads").select("*").eq(
                "user_id", user_id
            ).order("created_at", desc=True).execute()
            return [ThreadRecord.model_validate(row) for row in (result.data or [])]
        except Exception:
            return []

    async def add_message(self, thread_id: str, message: ChatMessage) -> None:
        payload = message.model_dump(mode="json")
        payload["thread_id"] = thread_id
        payload["created_at"] = payload.get("created_at") or _now()
        self._db().table("chat_messages").insert(payload).execute()

    async def get_thread_messages(self, thread_id: str, limit: int = 30) -> list[ChatMessage]:
        try:
            result = self._db().table("chat_messages").select(
                "role, content, retrieved_chunk_ids, created_at"
            ).eq("thread_id", thread_id).order("created_at", desc=True).limit(limit).execute()
            rows = list(reversed(result.data or []))
            return [ChatMessage.model_validate(row) for row in rows]
        except Exception:
            return []

    async def get_usage(self, user_id: str) -> UserUsage:
        try:
            result = self._db().table("user_usage").select("*").eq(
                "user_id", user_id
            ).limit(1).execute()
            if result.data:
                return UserUsage.model_validate(result.data[0])
        except Exception:
            pass
        return await self.set_usage(user_id)

    async def set_usage(
        self,
        user_id: str,
        *,
        new_peels_used: int | None = None,
        chat_messages_used: int | None = None,
        failed_jobs_count: int | None = None,
        plan: str | None = None,
    ) -> UserUsage:
        current = UserUsage(user_id=user_id)
        try:
            result = self._db().table("user_usage").select("*").eq(
                "user_id", user_id
            ).limit(1).execute()
            if result.data:
                current = UserUsage.model_validate(result.data[0])
        except Exception:
            pass
        payload = current.model_dump(mode="json")
        if new_peels_used is not None:
            payload["new_peels_used"] = new_peels_used
        if chat_messages_used is not None:
            payload["chat_messages_used"] = chat_messages_used
        if failed_jobs_count is not None:
            payload["failed_jobs_count"] = failed_jobs_count
        if plan is not None:
            payload["plan"] = plan
        self._db().table("user_usage").upsert(payload, on_conflict="user_id").execute()
        return UserUsage.model_validate(payload)


def build_repository():
    from config import PEELER_STORAGE

    if PEELER_STORAGE.lower() == "supabase":
        return SupabasePeelerRepository()
    return MemoryPeelerRepository()


repository = build_repository()

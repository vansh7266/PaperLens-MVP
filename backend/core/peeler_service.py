from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from inspect import isawaitable

from config import get_chat_limit, get_peel_limit
from core.peeler_llm import generate_openai_chat, generate_openai_peel
from core.peeler_models import (
    ChatMessage,
    PaperChunk,
    PaperRecord,
    PeelJob,
    PeelOutput,
)
from core.peeler_repository import MemoryPeelerRepository


PeelGenerator = Callable[[PaperRecord], PeelOutput | Awaitable[PeelOutput]]
ChatGenerator = Callable[[str, str], str | Awaitable[str]]


async def _maybe_await(value):
    if isawaitable(value):
        return await value
    return value


class QuotaExceededError(Exception):
    pass


class ThreadAccessError(Exception):
    pass


class PeelerService:
    def __init__(
        self,
        repo: MemoryPeelerRepository,
        peel_generator: PeelGenerator | None = None,
        chat_generator: ChatGenerator | None = None,
    ) -> None:
        self.repo = repo
        self.peel_generator = peel_generator
        self.chat_generator = chat_generator

    async def start_peel_job(self, user_id: str, paper: PaperRecord) -> PeelJob:
        job = await self.enqueue_peel_job(user_id, paper)
        if job.status == "completed":
            return job
        return await self.run_peel_job(job.job_id, paper)

    async def enqueue_peel_job(self, user_id: str, paper: PaperRecord) -> PeelJob:
        await self.repo.save_paper(paper)
        cached = await self.repo.get_global_peel(paper.canonical_id)
        if cached:
            thread = await self.repo.create_thread(
                user_id,
                paper.canonical_id,
                cached.paper_id,
                title=paper.title,
            )
            return await self.repo.create_job(
                PeelJob(
                    user_id=user_id,
                    paper_id=paper.canonical_id,
                    status="completed",
                    stage="served_from_cache",
                    progress=100,
                    thread_id=thread.thread_id,
                    completed_from_cache=True,
                    consumed_credit=False,
                )
            )

        await self._ensure_peel_quota(user_id)
        return await self.repo.create_job(
            PeelJob(
                user_id=user_id,
                paper_id=paper.canonical_id,
                status="queued",
                stage="queued",
                progress=0,
            )
        )

    async def run_peel_job(self, job_id: str, paper: PaperRecord) -> PeelJob:
        try:
            await self._stage(job_id, "resolving_identity", 10)
            await self.repo.save_paper(paper)
            await self._stage(job_id, "extracting_document", 22)
            chunks = await self._ensure_chunks(paper)
            await self._stage(job_id, "indexing_chunks", 35)
            await self._stage(job_id, "finding_related_papers", 48)
            await asyncio.sleep(0)
            await self._stage(job_id, "drawing_architecture", 62)
            await self._stage(job_id, "peeling_math", 74)
            await self._stage(job_id, "writing_analysis", 84)
            peel = await self._generate_peel(paper, chunks)
            await self._stage(job_id, "validating_evidence", 92)
            peel = peel.model_copy(update={"paper_id": paper.canonical_id})
            await self.repo.save_global_peel(peel)
            job_user = await self._job_user(job_id)
            await self.repo.increment_new_peels(job_user)
            thread = await self.repo.create_thread(
                job_user,
                paper.canonical_id,
                peel.paper_id,
                title=paper.title,
            )
            return await self.repo.update_job(
                job_id,
                status="completed",
                stage="saved_to_cache",
                progress=100,
                thread_id=thread.thread_id,
                completed_from_cache=False,
                consumed_credit=True,
            )
        except Exception as exc:
            job = await self.repo.get_job(job_id)
            if job:
                await self.repo.increment_failed_jobs(job.user_id)
            return await self.repo.update_job(
                job_id,
                status="failed",
                error_code="PEEL_FAILED",
                error_message=str(exc)[:300],
                consumed_credit=False,
            )

    async def answer_chat(self, user_id: str, thread_id: str, question: str) -> str:
        thread = await self.repo.get_thread(thread_id)
        if not thread or thread.user_id != user_id:
            raise ThreadAccessError("Thread not found for this user")
        await self._ensure_chat_quota(user_id)
        paper = await self.repo.get_paper(thread.paper_id)
        peel = await self.repo.get_global_peel(thread.peel_output_id)
        if not paper or not peel:
            raise ThreadAccessError("Paper context is unavailable")
        chunks = await self.repo.get_chunks(thread.paper_id)

        await self.repo.add_message(thread_id, ChatMessage(role="user", content=question))
        if self.chat_generator:
            answer = await _maybe_await(self.chat_generator(thread_id, question))
        else:
            answer = await generate_openai_chat(paper, peel, chunks, question)
        await self.repo.add_message(thread_id, ChatMessage(role="assistant", content=answer))
        await self.repo.increment_chat_messages(user_id)
        return answer

    async def _generate_peel(self, paper: PaperRecord, chunks: list[PaperChunk]) -> PeelOutput:
        if self.peel_generator:
            return await _maybe_await(self.peel_generator(paper))
        from core.peeler_history import find_related_context

        related_papers, related_context = await find_related_context(paper)
        peel = await generate_openai_peel(paper, chunks, related_context)
        if related_papers and (
            not peel.related_papers
            or peel.related_papers[0].title.startswith("Verified related papers pending")
        ):
            peel = peel.model_copy(update={"related_papers": related_papers})
        return peel

    async def _ensure_chunks(self, paper: PaperRecord) -> list[PaperChunk]:
        existing = await self.repo.get_chunks(paper.canonical_id)
        if existing:
            return existing

        # For arXiv-resolved papers, auto-download the PDF so the LLM gets the
        # full paper text instead of just the abstract. This is the difference
        # between a real complete teaching and a thin summary.
        if paper.source_type == "arxiv" and paper.arxiv_id:
            fetched = await self._fetch_arxiv_chunks(paper)
            if fetched:
                await self.repo.save_chunks(paper.canonical_id, fetched)
                return fetched

        text = paper.abstract or paper.title
        chunks = [
            PaperChunk(
                paper_id=paper.canonical_id,
                section="Abstract",
                text=text,
                extraction_quality=paper.extraction_quality or paper.confidence,
            )
        ]
        await self.repo.save_chunks(paper.canonical_id, chunks)
        return chunks

    async def _fetch_arxiv_chunks(self, paper: PaperRecord) -> list[PaperChunk]:
        """Download the arXiv PDF and run it through the existing extractor.
        Returns [] on any failure so the caller can fall back to abstract-only."""
        import logging

        log = logging.getLogger("peeler_service")
        url = paper.pdf_url or f"https://arxiv.org/pdf/{paper.arxiv_id}"
        try:
            import httpx

            from core.pdf_extractor import extract_uploaded_pdf

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
            if not content or not content.startswith(b"%PDF"):
                log.warning("arXiv fetch %s returned non-PDF content", url)
                return []
            _paper_meta, chunks = await extract_uploaded_pdf(f"{paper.arxiv_id}.pdf", content)
            # Rebind chunks to the resolved paper's canonical_id (the extractor uses upload:<sha>).
            rebound = [
                chunk.model_copy(update={"paper_id": paper.canonical_id})
                for chunk in chunks
            ]
            log.info("arXiv PDF chunks fetched: %s chunks for %s", len(rebound), paper.canonical_id)
            return rebound
        except Exception as exc:
            log.warning("arXiv PDF fetch failed for %s: %s", paper.canonical_id, exc)
            return []

    async def _ensure_peel_quota(self, user_id: str) -> None:
        usage = await self.repo.get_usage(user_id)
        limit = get_peel_limit(usage.plan)
        if limit >= 0 and usage.new_peels_used >= limit:
            raise QuotaExceededError("No new peel credits remaining")

    async def _ensure_chat_quota(self, user_id: str) -> None:
        usage = await self.repo.get_usage(user_id)
        limit = get_chat_limit(usage.plan)
        if limit >= 0 and usage.chat_messages_used >= limit:
            raise QuotaExceededError("No chat credits remaining")

    async def _stage(self, job_id: str, stage: str, progress: int) -> None:
        await self.repo.update_job(job_id, status="running", stage=stage, progress=progress)

    async def _job_user(self, job_id: str) -> str:
        job = await self.repo.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return job.user_id

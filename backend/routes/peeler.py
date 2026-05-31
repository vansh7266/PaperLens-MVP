from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import jwt

from config import DEBUG, get_chat_limit, get_peel_limit
from core.pdf_extractor import PdfExtractionError, extract_uploaded_pdf
from core.peeler_models import (
    ChatRequest,
    ResolveRequest,
    ResolveResponse,
    StartPeelRequest,
)
from core.peeler_repository import repository
from core.peeler_resolver import resolve_paper
from core.peeler_service import PeelerService, QuotaExceededError, ThreadAccessError


router = APIRouter(prefix="/api", tags=["Peeler"])
_peeler_bearer = HTTPBearer(auto_error=False)


# Peeler-specific auth: accept any JWT shape (no signature verify) for demo/dev,
# OR fall back to a stable dev user when DEBUG=true. Production keeps a real
# Supabase token; this only matters when the prototype is being demoed.
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_peeler_bearer),
) -> dict:
    if credentials and credentials.credentials:
        try:
            payload = jwt.decode(credentials.credentials, options={"verify_signature": False})
            user_id = payload.get("sub")
            email   = payload.get("email", "user@paperlens.local")
            if user_id:
                return {"sub": user_id, "email": email}
        except Exception:
            pass
    if DEBUG:
        # Stable dev user — same UUID every time so threads/usage accumulate
        return {"sub": "5304565f-0416-42e1-bfbe-fdf4ffd77a89", "email": "dev@paperlens.local"}
    raise HTTPException(status_code=401, detail="Authentication required.")
service = PeelerService(repository)
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    bucket = _rate_buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Try again soon.")
    bucket.append(now)



async def get_rate_limited_user(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    user_id = current_user["sub"]
    ip_hash = str(hash(request.client.host if request.client else "unknown"))
    device_hash = request.headers.get("x-device-hash", "missing")
    _rate_limit(f"user:{user_id}", limit=80, window_seconds=60)
    _rate_limit(f"ip:{ip_hash}", limit=160, window_seconds=60)
    _rate_limit(f"device:{device_hash}", limit=120, window_seconds=60)
    return current_user


@router.post("/peeler/resolve", response_model=ResolveResponse)
async def resolve_endpoint(
    payload: ResolveRequest,
    current_user: dict = Depends(get_rate_limited_user),
):
    response = await resolve_paper(payload.input, payload.input_type)
    if response.paper:
        response.cached = await repository.get_global_peel(response.paper.canonical_id) is not None
    for candidate in response.candidates:
        if await repository.get_global_peel(candidate.canonical_id):
            response.cached = True
    return response


@router.post("/peeler/upload")
async def upload_endpoint(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_rate_limited_user),
):
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
    content = await file.read()
    try:
        paper, chunks = await extract_uploaded_pdf(file.filename or "paper.pdf", content)
        await repository.save_paper(paper)
        await repository.save_chunks(paper.canonical_id, chunks)
        cached = await repository.get_global_peel(paper.canonical_id) is not None
        return {
            "status": "limited_context" if paper.is_private else "matched",
            "paper": paper.model_dump(),
            "cached": cached,
            "message": "Private upload will be peeled with limited historical context.",
        }
    except PdfExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/peeler/jobs")
async def create_job_endpoint(
    payload: StartPeelRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_rate_limited_user),
):
    user_id = current_user["sub"]
    try:
        job = await service.enqueue_peel_job(user_id, payload.paper)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    if job.status != "completed":
        background_tasks.add_task(service.run_peel_job, job.job_id, payload.paper)
    return job.model_dump()


@router.get("/peeler/jobs/{job_id}")
async def get_job_endpoint(
    job_id: str,
    current_user: dict = Depends(get_rate_limited_user),
):
    job = await repository.get_job(job_id)
    if not job or job.user_id != current_user["sub"]:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.model_dump()


@router.get("/peeler/threads")
async def list_threads_endpoint(current_user: dict = Depends(get_rate_limited_user)):
    threads = await repository.list_threads(current_user["sub"])
    return {"threads": [thread.model_dump() for thread in threads]}


@router.get("/peeler/threads/{thread_id}")
async def get_thread_endpoint(
    thread_id: str,
    current_user: dict = Depends(get_rate_limited_user),
):
    thread = await repository.get_thread(thread_id)
    if not thread or thread.user_id != current_user["sub"]:
        raise HTTPException(status_code=404, detail="Thread not found.")
    paper = await repository.get_paper(thread.paper_id)
    peel = await repository.get_global_peel(thread.peel_output_id)
    messages = await repository.get_thread_messages(thread_id)
    if not paper or not peel:
        raise HTTPException(status_code=404, detail="Paper analysis unavailable.")
    return {
        "thread": thread.model_dump(),
        "paper": paper.model_dump(),
        "peel": peel.model_dump(),
        "messages": [message.model_dump() for message in messages],
    }


@router.post("/peeler/threads/{thread_id}/chat/stream")
async def chat_stream_endpoint(
    thread_id: str,
    payload: ChatRequest,
    current_user: dict = Depends(get_rate_limited_user),
):
    user_id = current_user["sub"]

    async def event_stream() -> AsyncIterator[str]:
        try:
            answer = await service.answer_chat(user_id, thread_id, payload.question)
            words = answer.split(" ")
            for index, word in enumerate(words):
                chunk = word + (" " if index < len(words) - 1 else "")
                yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
                await asyncio.sleep(0.01)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except QuotaExceededError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except ThreadAccessError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/usage")
async def usage_endpoint(current_user: dict = Depends(get_rate_limited_user)):
    usage = await repository.get_usage(current_user["sub"])
    peel_limit = get_peel_limit(usage.plan)
    chat_limit = get_chat_limit(usage.plan)
    return {
        "plan": usage.plan,
        "new_peels_used": usage.new_peels_used,
        "new_peels_limit": peel_limit,
        "new_peels_remaining": max(peel_limit - usage.new_peels_used, 0) if peel_limit >= 0 else -1,
        "chat_messages_used": usage.chat_messages_used,
        "chat_messages_limit": chat_limit,
        "chat_messages_remaining": max(chat_limit - usage.chat_messages_used, 0) if chat_limit >= 0 else -1,
        "cached_peels_cost_credits": False,
        "cached_peel_message": "Already-peeled papers open instantly and do not use peel credits.",
    }

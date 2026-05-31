from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from core.peeler_models import Confidence, PaperRecord, ResolveResponse


ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def detect_input_type(raw: str) -> str:
    value = raw.strip()
    if "arxiv.org" in value or ARXIV_ID_RE.search(value):
        return "arxiv"
    if DOI_RE.search(value) or value.lower().startswith("doi:"):
        return "doi"
    return "title"


def extract_arxiv_id(raw: str) -> str | None:
    match = ARXIV_ID_RE.search(raw)
    if not match:
        return None
    return match.group(1)


def extract_doi(raw: str) -> str | None:
    match = DOI_RE.search(raw)
    if match:
        return match.group(0)
    return raw.removeprefix("doi:").strip() if raw.lower().startswith("doi:") else None


async def resolve_paper(raw: str, input_type: str = "auto") -> ResolveResponse:
    kind = detect_input_type(raw) if input_type == "auto" else input_type
    if kind == "arxiv":
        paper = await resolve_arxiv(raw)
        return ResolveResponse(status="exact" if paper else "not_found", paper=paper)
    if kind == "doi":
        paper = await resolve_doi(raw)
        return ResolveResponse(status="exact" if paper else "not_found", paper=paper)
    candidates = await search_title(raw)
    return ResolveResponse(
        status="candidates" if candidates else "not_found",
        candidates=candidates[:3],
        message="Choose the exact paper before peeling." if candidates else None,
    )


async def resolve_arxiv(raw: str) -> PaperRecord | None:
    arxiv_id = extract_arxiv_id(raw)
    if not arxiv_id:
        return None
    url = f"https://export.arxiv.org/api/query?id_list={quote(arxiv_id)}"
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
        title = _between(text, "<title>", "</title>", occurrence=1) or f"arXiv {arxiv_id}"
        summary = _between(text, "<summary>", "</summary>") or ""
        authors = re.findall(r"<author>\s*<name>(.*?)</name>\s*</author>", text, flags=re.DOTALL)
        published = _between(text, "<published>", "</published>")
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        return PaperRecord(
            canonical_id=f"arxiv:{arxiv_id}",
            source_type="arxiv",
            title=_clean_xml(title),
            authors=[_clean_xml(author) for author in authors],
            abstract=_clean_xml(summary),
            source_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=pdf_url,
            arxiv_id=arxiv_id,
            published_at=published,
            confidence=Confidence.HIGH,
        )
    except Exception:
        return PaperRecord(
            canonical_id=f"arxiv:{arxiv_id}",
            source_type="arxiv",
            title=f"arXiv {arxiv_id}",
            authors=[],
            source_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            arxiv_id=arxiv_id,
            confidence=Confidence.MEDIUM,
        )


async def resolve_doi(raw: str) -> PaperRecord | None:
    doi = extract_doi(raw)
    if not doi:
        return None
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(f"https://api.crossref.org/works/{quote(doi)}")
            response.raise_for_status()
            item = response.json()["message"]
        title = (item.get("title") or [doi])[0]
        authors = [
            " ".join(part for part in [author.get("given"), author.get("family")] if part)
            for author in item.get("author", [])
        ]
        year = None
        date_parts = item.get("published-print", item.get("published-online", {})).get("date-parts")
        if date_parts and date_parts[0]:
            year = str(date_parts[0][0])
        return PaperRecord(
            canonical_id=f"doi:{doi.lower()}",
            source_type="doi",
            title=title,
            authors=authors,
            abstract=item.get("abstract", ""),
            source_url=item.get("URL"),
            doi=doi,
            published_at=year,
            confidence=Confidence.HIGH,
        )
    except Exception:
        return PaperRecord(
            canonical_id=f"doi:{doi.lower()}",
            source_type="doi",
            title=doi,
            doi=doi,
            confidence=Confidence.MEDIUM,
        )


async def search_title(query: str) -> list[PaperRecord]:
    if len(query.strip()) < 3:
        return []
    # Primary: Semantic Scholar (richer metadata when it works)
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": 3,
            "fields": "title,authors,abstract,year,url,externalIds",
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json().get("data", [])
        if data:
            papers = []
            for item in data:
                external = item.get("externalIds") or {}
                arxiv_id = external.get("ArXiv")
                doi = external.get("DOI")
                canonical = f"arxiv:{arxiv_id}" if arxiv_id else f"semantic:{item.get('paperId')}"
                papers.append(
                    PaperRecord(
                        canonical_id=canonical,
                        source_type="title",
                        title=item.get("title") or query,
                        authors=[author.get("name", "") for author in item.get("authors", [])],
                        abstract=item.get("abstract") or "",
                        source_url=item.get("url"),
                        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
                        arxiv_id=arxiv_id,
                        doi=doi,
                        published_at=str(item.get("year")) if item.get("year") else None,
                        confidence=Confidence.MEDIUM,
                    )
                )
            return papers
    except Exception:
        pass

    # Fallback: arXiv search API (open, reliable — gives us a real title + authors)
    arxiv_papers = await _search_arxiv_by_title(query)
    if arxiv_papers:
        return arxiv_papers

    # Last resort: title-case the user's typed string so it at least looks like a title
    return [
        PaperRecord(
            canonical_id=f"title:{re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-')[:80]}",
            source_type="title",
            title=_smart_title_case(query),
            confidence=Confidence.LOW,
        )
    ]


async def _search_arxiv_by_title(query: str) -> list[PaperRecord]:
    """Search arXiv by title. Returns up to 3 candidates with proper title + authors."""
    cleaned = re.sub(r"\s+", " ", query.strip())
    if not cleaned:
        return []
    # AND across title words (un-quoted) — surfaces canonical matches even when
    # the user's wording is sloppy (e.g. "attention all you need" should still
    # hit "Attention Is All You Need").
    words = [w for w in re.split(r"\s+", cleaned) if w]
    search_query = " AND ".join(f"ti:{w}" for w in words) if words else f"ti:{cleaned}"
    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query={quote(search_query)}"
        "&start=0&max_results=3&sortBy=relevance&sortOrder=descending"
    )
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
    except Exception:
        return []

    # Split into <entry>...</entry> blocks
    entries = re.findall(r"<entry>(.*?)</entry>", text, flags=re.DOTALL)
    papers: list[PaperRecord] = []
    for entry in entries:
        id_match = re.search(r"<id>\s*http[s]?://arxiv\.org/abs/([^<\s]+)\s*</id>", entry)
        if not id_match:
            continue
        raw_id = id_match.group(1).strip()
        arxiv_id = re.sub(r"v\d+$", "", raw_id)
        title = _clean_xml(_between(entry, "<title>", "</title>") or "")
        summary = _clean_xml(_between(entry, "<summary>", "</summary>") or "")
        authors = [
            _clean_xml(a)
            for a in re.findall(r"<author>\s*<name>(.*?)</name>\s*</author>", entry, flags=re.DOTALL)
        ]
        published = _between(entry, "<published>", "</published>")
        year = published[:4] if published else None
        papers.append(
            PaperRecord(
                canonical_id=f"arxiv:{arxiv_id}",
                source_type="title",
                title=title or _smart_title_case(query),
                authors=authors,
                abstract=summary,
                source_url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                arxiv_id=arxiv_id,
                published_at=year,
                confidence=Confidence.HIGH,
            )
        )
    return papers


_SMALL_WORDS = {"a", "an", "the", "and", "or", "but", "for", "nor", "on", "at",
                "to", "by", "of", "in", "is", "as", "it"}


def _smart_title_case(text: str) -> str:
    words = re.split(r"(\s+)", text.strip())
    out = []
    word_index = 0
    for token in words:
        if token.isspace() or not token:
            out.append(token)
            continue
        lower = token.lower()
        if word_index > 0 and lower in _SMALL_WORDS:
            out.append(lower)
        else:
            out.append(token[:1].upper() + token[1:].lower() if len(token) > 1 else token.upper())
        word_index += 1
    return "".join(out)


def _between(text: str, start: str, end: str, occurrence: int = 0) -> str | None:
    idx = -1
    offset = 0
    for _ in range(occurrence + 1):
        idx = text.find(start, offset)
        if idx < 0:
            return None
        offset = idx + len(start)
    final = text.find(end, offset)
    if final < 0:
        return None
    return text[offset:final]


def _clean_xml(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")).strip()

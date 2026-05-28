from __future__ import annotations

from urllib.parse import quote

import httpx

from core.peeler_models import PaperRecord, RelatedPaper


SEMANTIC_FIELDS = (
    "title,year,authors,abstract,citationCount,externalIds,"
    "references.title,references.year,references.authors,"
    "references.abstract,references.citationCount,references.externalIds"
)


async def find_related_context(paper: PaperRecord) -> tuple[list[RelatedPaper], str]:
    """
    Fetch verified prior work from scholarly APIs only.

    V1 intentionally avoids random web search for lineage so the model can only
    discuss papers returned by Semantic Scholar/OpenAlex or explicitly cited.
    """
    related = await _semantic_scholar_references(paper)
    if len(related) < 3:
        related.extend(await _openalex_related(paper, limit=6 - len(related)))

    # Filter the current paper out (S2 sometimes self-includes; OpenAlex returns
    # the current paper as the top result when searching by its own title).
    current_title = (paper.title or "").strip().lower()
    current_arxiv = (paper.arxiv_id or "").strip().lower()
    current_doi = (paper.doi or "").strip().lower()

    def _is_self(item: RelatedPaper) -> bool:
        if current_title and item.title.strip().lower() == current_title:
            return True
        sid = (item.source_id or "").strip().lower()
        if current_arxiv and current_arxiv in sid:
            return True
        if current_doi and current_doi in sid:
            return True
        return False

    deduped: list[RelatedPaper] = []
    seen: set[str] = set()
    for item in related:
        if _is_self(item):
            continue
        key = (item.source_id or item.title).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 6:
            break

    # Build a rich context block for the LLM so it can write detailed
    # summary / had / problem / solved-by-this lineage for each prior paper.
    # We keep this human-readable JSON-ish format so the LLM can copy fields
    # straight into the related_papers output array.
    lines: list[str] = []
    for index, item in enumerate(deduped, start=1):
        authors = ", ".join(item.authors[:3]) if item.authors else "Authors unknown"
        abstract = (item.what_it_tried or "").strip().replace("\n", " ")
        if len(abstract) > 900:
            abstract = abstract[:900] + "…"
        source_hint = f" (source_id: {item.source_id})" if item.source_id else ""
        lines.append(
            f"[REF {index}] {item.title}{source_hint}\n"
            f"  year: {item.year or 'Unknown'}\n"
            f"  authors: {authors}\n"
            f"  abstract: {abstract or '(no abstract available)'}"
        )
    context = "\n\n".join(lines)
    return deduped, context


async def _semantic_scholar_references(paper: PaperRecord) -> list[RelatedPaper]:
    paper_key = _semantic_key(paper)
    if not paper_key:
        return []

    url = f"https://api.semanticscholar.org/graph/v1/paper/{quote(paper_key)}"
    params = {"fields": SEMANTIC_FIELDS}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    references = payload.get("references") or []
    references = [
        ref for ref in references
        if ref.get("title") and (not paper.published_at or _is_prior(ref.get("year"), paper.published_at))
    ]
    references.sort(key=lambda ref: ref.get("citationCount") or 0, reverse=True)
    return [_related_from_semantic(ref) for ref in references[:8]]


async def _openalex_related(paper: PaperRecord, limit: int = 4) -> list[RelatedPaper]:
    if limit <= 0:
        return []
    url = "https://api.openalex.org/works"
    params = {
        "search": paper.title,
        "per-page": limit,
        "sort": "cited_by_count:desc",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    items = []
    for work in payload.get("results") or []:
        title = work.get("title")
        if not title or title.lower() == paper.title.lower():
            continue
        authorships = work.get("authorships") or []
        authors = [
            item.get("author", {}).get("display_name")
            for item in authorships[:4]
            if item.get("author", {}).get("display_name")
        ]
        items.append(RelatedPaper(
            title=title,
            year=work.get("publication_year"),
            authors=authors,
            source_id=work.get("id"),
            what_it_tried=(work.get("abstract_inverted_index") and "Related scholarly work found by OpenAlex") or "",
            limitation="Limitation must be inferred from the paper context; no unsupported claim is made.",
            connection_to_this_paper="Related by scholarly search over the submitted paper title.",
        ))
    return items[:limit]


def _semantic_key(paper: PaperRecord) -> str | None:
    if paper.arxiv_id:
        return f"ARXIV:{paper.arxiv_id}"
    if paper.canonical_id.startswith("arxiv:"):
        return f"ARXIV:{paper.canonical_id.split(':', 1)[1]}"
    if paper.doi:
        return f"DOI:{paper.doi}"
    if paper.canonical_id.startswith("doi:"):
        return f"DOI:{paper.canonical_id.split(':', 1)[1]}"
    if paper.title:
        return paper.title
    return None


def _related_from_semantic(ref: dict) -> RelatedPaper:
    authors = [
        author.get("name")
        for author in (ref.get("authors") or [])[:4]
        if author.get("name")
    ]
    abstract = ref.get("abstract") or ""
    external = ref.get("externalIds") or {}
    source_id = external.get("ArXiv") or external.get("DOI") or ref.get("paperId")
    return RelatedPaper(
        title=ref.get("title") or "Untitled related paper",
        year=ref.get("year"),
        authors=authors,
        source_id=source_id,
        what_it_tried=abstract[:300],
        limitation="Limitation should be stated only if the submitted paper or related abstract supports it.",
        connection_to_this_paper="Cited by the submitted paper.",
        evidence=[source_id] if source_id else [],
    )


def _is_prior(year: int | None, published_at: str | None) -> bool:
    if not year or not published_at:
        return True
    return str(year) <= str(published_at)[:4]

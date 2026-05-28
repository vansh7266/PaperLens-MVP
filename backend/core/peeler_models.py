from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceChip(BaseModel):
    label: str
    source: Literal["paper", "related_paper", "metadata", "extraction"] = "paper"
    text: str = Field(default="", max_length=500)
    chunk_id: str | None = None
    location: str | None = None

    @classmethod
    def coerce(cls, v: Any) -> "EvidenceChip":
        """Accept plain strings from LLM output."""
        if isinstance(v, str):
            return cls(label=v[:120], text=v[:500])
        if isinstance(v, dict):
            return cls.model_validate(v)
        return v


class PaperRecord(BaseModel):
    canonical_id: str
    source_type: Literal["arxiv", "doi", "title", "pdf_upload", "feed", "private_upload"]
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    source_url: str | None = None
    pdf_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    published_at: str | None = None
    topic: str = "General_AI"
    difficulty: str = "Intermediate"
    confidence: Confidence = Confidence.MEDIUM
    extraction_quality: Confidence | None = None
    is_private: bool = False


class PaperChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: f"chunk_{uuid4().hex}")
    paper_id: str
    section: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    extraction_quality: Confidence = Confidence.MEDIUM


def _coerce_confidence(v: Any) -> str:
    """Accept float 0-1 or string confidence values from LLM output."""
    if isinstance(v, float) or isinstance(v, int):
        f = float(v)
        if f >= 0.67: return "high"
        if f >= 0.34: return "medium"
        return "low"
    if isinstance(v, str):
        v = v.lower().strip()
        if v in ("high", "very high", "very_high"): return "high"
        if v in ("medium", "moderate", "mid"):      return "medium"
        return "low"
    return "medium"


class PeelSection(BaseModel):
    title: str
    body: str
    confidence: Confidence = Confidence.MEDIUM
    evidence: list[EvidenceChip] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: Any) -> str:
        return _coerce_confidence(v)

    @field_validator("evidence", mode="before")
    @classmethod
    def coerce_evidence(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [EvidenceChip.coerce(item) if not isinstance(item, EvidenceChip) else item for item in v]


class ArchitectureGraph(BaseModel):
    # Stage 1 — simple view: 4-6 abstract blocks
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    reveal_order: list[str] = Field(default_factory=list)
    node_explanations: dict[str, str] = Field(default_factory=dict)
    data_flow_steps: list[str] = Field(default_factory=list)
    # Stage 2 — expanded view: detailed sub-blocks revealed after "peel this"
    expanded_nodes: list[dict[str, Any]] = Field(default_factory=list)
    expanded_edges: list[dict[str, Any]] = Field(default_factory=list)
    # Maps each simple_view node id → list of expanded_view node ids that belong inside it
    expansion_map: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("nodes", mode="before")
    @classmethod
    def coerce_nodes(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for i, item in enumerate(v):
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                node_id = item.lower().replace(" ", "_").replace("-", "_")[:32]
                result.append({"id": node_id, "label": item, "type": "module"})
        return result

    @field_validator("edges", mode="before")
    @classmethod
    def coerce_edges(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                # Try to parse "A to B" or "A -> B" format
                for sep in (" to ", " -> ", "->", "→"):
                    if sep in item:
                        parts = item.split(sep, 1)
                        result.append({
                            "from": parts[0].strip().lower().replace(" ", "_")[:32],
                            "to": parts[1].strip().lower().replace(" ", "_")[:32],
                        })
                        break
        return result

    @field_validator("reveal_order", mode="before")
    @classmethod
    def coerce_reveal_order(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [str(item) for item in v]

    @field_validator("node_explanations", mode="before")
    @classmethod
    def coerce_node_explanations(cls, v: Any) -> dict:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}

    @field_validator("expanded_nodes", mode="before")
    @classmethod
    def coerce_expanded_nodes(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                node_id = item.lower().replace(" ", "_").replace("-", "_")[:48]
                result.append({"id": node_id, "label": item, "type": "module"})
        return result

    @field_validator("expanded_edges", mode="before")
    @classmethod
    def coerce_expanded_edges(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                for sep in (" to ", " -> ", "->", "→"):
                    if sep in item:
                        parts = item.split(sep, 1)
                        result.append({
                            "from": parts[0].strip().lower().replace(" ", "_")[:48],
                            "to": parts[1].strip().lower().replace(" ", "_")[:48],
                        })
                        break
        return result

    @field_validator("expansion_map", mode="before")
    @classmethod
    def coerce_expansion_map(cls, v: Any) -> dict:
        if not isinstance(v, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, val in v.items():
            key = str(k)
            if isinstance(val, list):
                out[key] = [str(x) for x in val]
            elif isinstance(val, str):
                out[key] = [val]
        return out

    @model_validator(mode="after")
    def validate_graph_refs(self) -> "ArchitectureGraph":
        node_ids = {str(node.get("id")) for node in self.nodes if node.get("id")}
        # Silently drop invalid edges rather than failing
        self.edges = [e for e in self.edges if e.get("from") in node_ids and e.get("to") in node_ids]
        # Silently drop invalid reveal_order refs
        self.reveal_order = [r for r in self.reveal_order if r in node_ids]
        # Expanded view validation
        expanded_ids = {str(node.get("id")) for node in self.expanded_nodes if node.get("id")}
        self.expanded_edges = [
            e for e in self.expanded_edges
            if e.get("from") in expanded_ids and e.get("to") in expanded_ids
        ]
        # Filter expansion_map: only keep entries that map known simple_view ids to known expanded ids
        clean_map: dict[str, list[str]] = {}
        for simple_id, child_ids in self.expansion_map.items():
            if simple_id not in node_ids:
                continue
            valid_children = [cid for cid in child_ids if cid in expanded_ids]
            if valid_children:
                clean_map[simple_id] = valid_children
        self.expansion_map = clean_map
        return self


class MathSymbol(BaseModel):
    symbol: str
    meaning: str


class MathPeelEquation(BaseModel):
    latex: str
    location: str | None = None
    symbols: list[MathSymbol] = Field(default_factory=list)
    plain_meaning: str = ""
    role_in_architecture: str = ""
    behavior_if_changed: str = ""
    evidence: list[EvidenceChip] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def coerce_evidence(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [EvidenceChip.coerce(item) if not isinstance(item, EvidenceChip) else item for item in v]

    @field_validator("symbols", mode="before")
    @classmethod
    def coerce_symbols(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict) and "symbol" in item and "meaning" in item:
                result.append(MathSymbol(**item))
            elif isinstance(item, str):
                parts = item.split(":", 1)
                result.append(MathSymbol(symbol=parts[0].strip(), meaning=parts[1].strip() if len(parts) > 1 else item))
        return result


class RelatedPaper(BaseModel):
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    source_id: str | None = None
    # Detailed lineage — populated by the LLM after reading abstracts of S2 references
    summary: str = ""                       # 80-120 word plain-English summary of this prior paper
    what_it_tried: str = ""                 # What the paper contributed / had / proposed
    limitation: str = ""                    # Its problem / gap / limitation
    connection_to_this_paper: str = ""      # How the current paper fixes / extends / supersedes it
    evidence: list[str] = Field(default_factory=list)


REQUIRED_SECTIONS = {"what", "timeline", "fixes", "architecture", "results", "verdict"}


class PeelOutput(BaseModel):
    paper_id: str
    schema_version: str = "1.0"
    sections: dict[str, PeelSection]
    architecture: ArchitectureGraph
    math_peel: list[MathPeelEquation] = Field(default_factory=list)
    related_papers: list[RelatedPaper] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_used: str = "local-dev"
    completed_from_cache: bool = False

    @field_validator("schema_version", mode="before")
    @classmethod
    def coerce_schema_version(cls, v: Any) -> str:
        return str(v)

    @field_validator("math_peel", mode="before")
    @classmethod
    def coerce_math_peel(cls, v: Any) -> list:
        if isinstance(v, dict):
            # LLM wrapped it: {"equations": [...]} or {"math_peel": [...]}
            for key in ("equations", "math_peel", "items"):
                if key in v and isinstance(v[key], list):
                    v = v[key]
                    break
            else:
                return []
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                # Plain LaTeX string — wrap it into a minimal MathPeelEquation dict
                result.append({
                    "latex": item,
                    "plain_meaning": "See equation above.",
                    "role_in_architecture": "Core method equation.",
                    "behavior_if_changed": "Changes the model's computation.",
                    "symbols": [],
                    "evidence": [],
                })
        return result

    @field_validator("sections", mode="before")
    @classmethod
    def require_six_sections(cls, value: Any) -> Any:
        if isinstance(value, dict):
            missing = REQUIRED_SECTIONS - set(value.keys())
            for key in missing:
                value[key] = {"title": key.title(), "body": "Not extracted.", "confidence": "medium", "evidence": []}
        return value

    @field_validator("suggested_questions", mode="before")
    @classmethod
    def normalize_questions(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return ["What is the central contribution?", "Which part matters most?",
                    "Which equations should I understand first?", "What would make this useful in practice?"]
        qs = [str(q) for q in value if q]
        # Pad to 4 if short
        defaults = ["What is the central contribution?", "Which part matters most?",
                    "Which equations should I understand first?", "What would make this useful in practice?"]
        while len(qs) < 4:
            qs.append(defaults[len(qs) % len(defaults)])
        return qs[:4]

    @field_validator("math_peel")
    @classmethod
    def cap_math_peel(cls, value: list[MathPeelEquation]) -> list[MathPeelEquation]:
        if len(value) > 5:
            raise ValueError("Math Peel should include at most 5 key equations in v1")
        return value


class UserUsage(BaseModel):
    user_id: str
    plan: Literal["free", "pro", "team"] = "free"
    new_peels_used: int = 0
    chat_messages_used: int = 0
    failed_jobs_count: int = 0
    period_start: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    period_end: str | None = None


class PeelJob(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_{uuid4().hex}")
    user_id: str
    paper_id: str | None = None
    status: Literal["queued", "running", "requires_confirmation", "limited_context", "completed", "failed"] = "queued"
    stage: str = "queued"
    progress: int = 0
    error_code: str | None = None
    error_message: str | None = None
    thread_id: str | None = None
    completed_from_cache: bool = False
    consumed_credit: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ThreadRecord(BaseModel):
    thread_id: str = Field(default_factory=lambda: f"thread_{uuid4().hex}")
    user_id: str
    paper_id: str
    peel_output_id: str
    title: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None


class ResolveRequest(BaseModel):
    input: str
    input_type: Literal["auto", "arxiv", "doi", "title", "feed"] = "auto"


class ResolveResponse(BaseModel):
    status: Literal["exact", "candidates", "not_found"]
    paper: PaperRecord | None = None
    candidates: list[PaperRecord] = Field(default_factory=list)
    cached: bool = False
    message: str | None = None


class StartPeelRequest(BaseModel):
    paper: PaperRecord


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

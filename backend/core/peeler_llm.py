from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from config import MODELS, OPENAI_API_KEY, GROQ_API_KEY
from core.peeler_models import (
    ArchitectureGraph,
    Confidence,
    EvidenceChip,
    MathPeelEquation,
    MathSymbol,
    PaperChunk,
    PaperRecord,
    PeelOutput,
    PeelSection,
    RelatedPaper,
)


def build_local_peel(paper: PaperRecord, chunks: list[PaperChunk] | None = None) -> PeelOutput:
    """
    Deterministic fallback for local testing when OPENAI_API_KEY is unavailable.
    It preserves the strict schema so frontend/backend flows can be verified
    before paid API credentials are added.
    """
    evidence = [
        EvidenceChip(
            label="Abstract",
            source="paper",
            text=(paper.abstract or paper.title)[:240],
            chunk_id=chunks[0].chunk_id if chunks else None,
            location=chunks[0].section if chunks else "metadata",
        )
    ]
    topic = paper.topic or "AI/ML"
    intro = (
        f"{paper.title} is treated as a {topic} research paper. "
        f"The current local analysis uses the available abstract and extracted text; "
        f"add OPENAI_API_KEY for the full launch-grade peel."
    )
    sections = {
        "what": PeelSection(
            title="What is this paper?",
            body=f"{intro} It focuses on: {paper.abstract[:500] if paper.abstract else 'the method described in the uploaded paper.'}",
            confidence=paper.confidence,
            evidence=evidence,
        ),
        "timeline": PeelSection(
            title="What came before?",
            body="Verified historical lineage needs Semantic Scholar/OpenAlex results. This local fallback shows the timeline area without inventing prior papers.",
            confidence=Confidence.LOW,
            evidence=[],
        ),
        "fixes": PeelSection(
            title="What does this paper fix?",
            body="The paper appears to address a gap in prior model design or evaluation. Full gap analysis is generated after OpenAI and scholarly API keys are connected.",
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
        "architecture": PeelSection(
            title="Architecture explained simply",
            body="PaperLens maps the method into input, representation, core mechanism, and output layers so users can follow the data flow.",
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
        "results": PeelSection(
            title="Results and benchmarks",
            body="Benchmark extraction is reserved for the validated model pass. The UI will show benchmark rows with evidence chips when numbers are found.",
            confidence=Confidence.LOW,
            evidence=[],
        ),
        "verdict": PeelSection(
            title="Should you care?",
            body="Care if this paper is close to your current research or engineering problem. The production peel will add limitations, target audience, and practical impact.",
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
    }
    return PeelOutput(
        paper_id=paper.canonical_id,
        sections=sections,
        architecture=ArchitectureGraph(
            nodes=[
                {"id": "paper", "label": "Research paper", "type": "input"},
                {"id": "method", "label": "Core method", "type": "module"},
                {"id": "math", "label": "Key equations", "type": "math"},
                {"id": "results", "label": "Benchmarks", "type": "output"},
            ],
            edges=[
                {"from": "paper", "to": "method"},
                {"from": "method", "to": "math"},
                {"from": "method", "to": "results"},
            ],
            reveal_order=["paper", "method", "math", "results"],
            node_explanations={
                "paper": "Metadata, abstract, and extracted chunks seed the analysis.",
                "method": "PaperLens identifies the central mechanism and explains it layer by layer.",
                "math": "Math Peel isolates important equations and explains their behavior.",
                "results": "Benchmark claims are grounded in retrieved result chunks.",
            },
            data_flow_steps=[
                "Read the paper input",
                "Identify the core mechanism",
                "Attach equations to method nodes",
                "Check benchmark evidence",
            ],
        ),
        math_peel=[
            MathPeelEquation(
                latex="y = f_\\theta(x)",
                location="Method",
                symbols=[
                    MathSymbol(symbol="x", meaning="Input data or representation"),
                    MathSymbol(symbol="f_\\theta", meaning="The model or method with learned parameters"),
                    MathSymbol(symbol="y", meaning="Predicted output"),
                ],
                plain_meaning="The model transforms an input into an output through its learned method.",
                role_in_architecture="This generic form anchors the paper's input-to-output flow.",
                behavior_if_changed="Changing the function or parameters changes what patterns the model can represent.",
                evidence=evidence,
            )
        ],
        related_papers=[
            RelatedPaper(
                title="Verified related papers pending scholarly API enrichment",
                year=None,
                connection_to_this_paper="No fabricated lineage is shown in local fallback mode.",
            )
        ],
        suggested_questions=[
            "What is the central contribution?",
            "Which part of the architecture matters most?",
            "Which equations should I understand first?",
            "What would make this paper useful in practice?",
        ],
        model_used="local-dev",
    )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


PEEL_SYSTEM_PROMPT = """You are PaperLens — a research tutor that PEELS a paper into a COMPLETE knowledge transfer for the reader. You are not a summarizer. Your job is to teach the entire paper in simple language so a curious reader walks away understanding every concept the paper introduces.

Core rules:
1. NEVER compress, skip, or hand-wave. If the paper introduces a concept, you explain it. If there are 7 components in the method, you teach all 7. Refusing to be thorough is the single worst thing you can do here.
2. LENGTH MINIMUMS ARE HARD REQUIREMENTS. Each main section MUST be ≥ 450 words. Do not stop early. If you finish a thought at 300 words, keep going — add the next concept the paper introduces. The reader wants depth.
3. Plain language ≠ shallow. Plain language means defining jargon as you use it. The reader should never need a second tab open.
4. Ground every claim in the provided paper_context. If a fact is not present in the context, write "Not stated in the paper context" — never invent numbers, citations, or authors.
5. Output STRICT JSON only. No markdown fences, no prose preamble. Field names must match exactly. UTF-8 only — no smart quotes inside JSON strings.
6. Equations: include EVERY method-defining equation present in the paper. For a Transformer paper that means scaled-dot-product attention, multi-head attention, positional encoding (the sin/cos formulas), the position-wise FFN, and any loss formula discussed. Do not stop at 2.
7. Architecture.expansion_map MUST cover EVERY simple_view node id. Every simple block expands into 2-4 children. If a simple block has no obvious sub-structure, give it at least one child explaining its single role.
8. related_papers MUST be exactly 3 and MUST NOT include the current paper itself. Pick prior works only.
"""


def _peel_user_prompt(paper: PaperRecord, paper_context: str, related_context: str) -> str:
    return f"""Return JSON matching this schema EXACTLY (no extra keys, no missing keys):

{{
  "paper_id": "<echo back the paper canonical_id>",
  "schema_version": "1.0",
  "model_used": "<filled by system, leave empty string>",
  "sections": {{
    "what":         {{ "title": "What this paper does",          "body": "<450-750 words>", "confidence": "high|medium|low", "evidence": [{{ "label": "<short>", "text": "<paper snippet ≤500 chars>", "location": "<section name>" }}] }},
    "timeline":     {{ "title": "What came before",              "body": "<450-750 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "fixes":        {{ "title": "What this paper fixes",         "body": "<450-750 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "architecture": {{ "title": "How the architecture works",    "body": "<450-750 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "results":      {{ "title": "Results and benchmarks",        "body": "<350-650 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "verdict":      {{ "title": "Should you care",               "body": "<300-500 words>", "confidence": "high|medium|low", "evidence": [...] }}
  }},
  "architecture": {{
    "nodes":             [<4-6 simple-view blocks: {{ "id": "<snake_case_id>", "label": "<Human Name>", "type": "input|module|attention|output|loss" }}>],
    "edges":             [<connections: {{ "from": "<simple_id>", "to": "<simple_id>" }}>],
    "reveal_order":      [<simple_node_ids in the order they should animate in>],
    "node_explanations": {{ "<simple_id>": "<2-4 sentence plain-English explanation of this block's role>" }},
    "data_flow_steps":   [<4-7 step-by-step narration strings, e.g., "Tokens are embedded into vectors", "Positional info is added", ...>],
    "expanded_nodes":    [<8-18 detailed sub-blocks that live INSIDE the simple_view blocks; same shape as nodes, ids should be like "<simple_id>.<sub>" e.g. "encoder.self_attention">],
    "expanded_edges":    [<connections between expanded_nodes>],
    "expansion_map":     {{ "<simple_id>": [<expanded_node_ids that belong inside this simple block>] }}
  }},
  "math_peel": [
    <ALL important equations from the paper (up to 8). Each item:
     {{
       "latex": "<clean LaTeX, no \\$ delimiters>",
       "location": "<Section name or Equation N>",
       "symbols": [{{ "symbol": "<latex symbol e.g. Q>", "meaning": "<what this symbol represents in the paper>" }}],
       "plain_meaning": "<2-4 sentences in plain English: what this equation computes and why>",
       "role_in_architecture": "<which simple/expanded architecture block uses this equation and how>",
       "behavior_if_changed": "<concrete consequence if you remove or modify a key term — be specific>",
       "evidence": [{{ "label": "Equation", "text": "<paper snippet ≤500 chars>", "location": "<section>" }}]
     }}>
  ],
  "related_papers": [
    <EXACTLY 3 of the most influential prior papers from the related_context below. Pick the ones the current paper builds on most directly. Each item:
     {{
       "title": "<from related_context>",
       "year": <int|null>,
       "authors": [<from related_context>],
       "source_id": "<from related_context>",
       "summary": "<80-120 word plain-English summary of THAT prior paper, written from the related_context abstract>",
       "what_it_tried": "<2-3 sentences: what contribution / mechanism that prior paper introduced>",
       "limitation": "<2-3 sentences: the specific problem / gap / weakness that prior paper had>",
       "connection_to_this_paper": "<3-5 sentences: how the CURRENT paper fixes / extends / supersedes this prior work. Be concrete — name the specific change.>",
       "evidence": ["<source_id or 'Cited prior work'>"]
     }}>
  ],
  "suggested_questions": [<exactly 4 deep paper-specific questions a curious reader would ask after the walkthrough>]
}}

WRITING INSTRUCTIONS:

[sections.what]  Teach the whole paper end-to-end in simple language. Cover: (1) the problem the paper attacks, (2) why prior methods are not enough, (3) the core idea of this paper in one sentence, (4) every major component of the method (one paragraph each), (5) the headline result. Do not skip components — if the paper has Multi-Head Attention + Positional Encoding + Encoder + Decoder + Layer Norm + Residuals, all six get explained.

[sections.timeline]  Tell the story of what came before. Reference the 3 papers you selected for related_papers, by title, and explain how the field evolved up to this paper. End with: "Which is exactly where this paper enters."

[sections.fixes]  Be specific. What was broken? What did this paper change? Which prior assumption did it discard? Explain the mechanism of the fix in plain English.

[sections.architecture]  Walk through the architecture in reading order — input first, output last. For every simple_view block you list in `architecture.nodes`, write a paragraph here that mirrors `node_explanations[id]` but with more depth. End by describing the data flow as a short story.

[sections.results]  Quote the actual numbers from the paper (BLEU, accuracy, perplexity, FLOPs, training time, etc.). For each number, say which dataset, which baseline it beats, and by how much. If the paper has ablations, mention them.

[sections.verdict]  Who is this for? When should a reader USE this paper? What's the practical takeaway? What are honest limitations (look for the paper's own "limitations" or "discussion" section)?

[architecture.expanded_nodes]  This is the "peel" view. After the simple_view animates, the user clicks "peel this" and each simple block expands. Each simple block should expand into 2-4 children. Example for a Transformer encoder:
  simple node "encoder" → expanded children: "encoder.embedding", "encoder.positional", "encoder.multihead_attn", "encoder.feedforward", "encoder.layernorm_residual"

[math_peel]  Include every equation that defines the method. For Transformer that means: scaled dot-product attention, multi-head attention, positional encoding sin/cos, FFN, label smoothing loss if discussed. Do not skip "small" equations if they are part of the method.

[related_papers.summary]  Write the summary FROM the abstract provided in related_context. Do not invent. If an abstract is missing, write a 1-line entry stating that.

[confidence]  Use "high" only when the paper context directly supports your text. Use "medium" when you have to infer. Use "low" when the paper context is thin on the topic. Be honest — the UI uses this to badge sections.

GIVEN INPUTS:

== Paper metadata ==
{paper.model_dump_json()}

== Paper context (chunks extracted from the actual paper) ==
{paper_context}

== Related context (prior works fetched from Semantic Scholar) ==
{related_context if related_context.strip() else "(no related context available — write related_papers as an empty array)"}
"""


# Sections we always want if present — they carry the method+results signal.
_PREFERRED_SECTION_HINTS = (
    "abstract", "introduction", "background", "related",
    "method", "model", "architecture", "approach",
    "experiment", "training", "evaluation", "result",
    "ablation", "analysis", "discussion", "conclusion",
)
# Sections to skip — they're boilerplate and burn token budget.
_SKIP_SECTION_HINTS = (
    "acknowledg", "reference", "bibliography", "appendix",
    "author contribution", "supplementary",
)


def _select_chunks_for_prompt(chunks: list[PaperChunk], char_budget: int = 24000, chunk_cap: int = 2400) -> str:
    """Pick the most informative chunks, drop boilerplate, fit a char budget.
    Order: preferred sections first (by appearance), then everything else.
    Caps each chunk to `chunk_cap` chars to give wide section coverage."""
    def is_skip(name: str) -> bool:
        n = name.lower()
        return any(hint in n for hint in _SKIP_SECTION_HINTS)

    def is_preferred(name: str) -> bool:
        n = name.lower()
        return any(hint in n for hint in _PREFERRED_SECTION_HINTS)

    preferred: list[PaperChunk] = []
    others: list[PaperChunk] = []
    for chunk in chunks:
        if is_skip(chunk.section):
            continue
        if is_preferred(chunk.section):
            preferred.append(chunk)
        else:
            others.append(chunk)

    selected: list[str] = []
    used = 0
    for chunk in preferred + others:
        if used >= char_budget:
            break
        text = chunk.text[:chunk_cap]
        header = f"[{chunk.section}]"
        block = f"{header} {text}"
        # Hard stop if this block would push past the budget — trim it.
        if used + len(block) > char_budget:
            block = block[: max(0, char_budget - used)]
        if block.strip():
            selected.append(block)
            used += len(block)
    return "\n\n".join(selected)


async def generate_openai_peel(
    paper: PaperRecord,
    chunks: list[PaperChunk],
    related_context: str = "",
) -> PeelOutput:
    """Generate a complete PaperLens peel.

    Depth scales with the provider:
      • OpenAI (production)  — 48k chars of paper context, 10k output tokens
                                → 450-700 word sections, all equations, deep lineage.
      • Groq free tier (dev) — 14k chars, 4500 output tokens (TPM=12k limit)
                                → 200-300 word sections, ~2-4 equations.
                                Content is still grounded and coherent, just less exhaustive.
    Switch GROQ → OpenAI by setting OPENAI_API_KEY in .env. No code change needed.
    """
    api_key = OPENAI_API_KEY
    base_url = None
    model = MODELS.get("openai", "gpt-5-mini")
    # OpenAI defaults — full depth.
    paper_char_budget = 48000
    per_chunk_cap = 3500
    output_max_tokens = 10000

    if not api_key and GROQ_API_KEY:
        api_key = GROQ_API_KEY
        base_url = "https://api.groq.com/openai/v1"
        model = MODELS.get("groq", "llama-3.1-8b-instant")
        # Groq free tier: 12k TPM on llama-3.3-70b-versatile. Stay under ~6k input tokens.
        paper_char_budget = 14000
        per_chunk_cap = 1800
        output_max_tokens = 4500

    if not api_key:
        return build_local_peel(paper, chunks)

    try:
        from openai import AsyncOpenAI
    except Exception:
        return build_local_peel(paper, chunks)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    paper_context = _select_chunks_for_prompt(chunks, char_budget=paper_char_budget, chunk_cap=per_chunk_cap)

    user_prompt = _peel_user_prompt(paper, paper_context, related_context)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PEEL_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=output_max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        payload = _extract_json(content)
        payload["paper_id"] = paper.canonical_id
        payload["model_used"] = model
        # Belt-and-suspenders: filter out the current paper if the LLM/related-fetch
        # accidentally included it in related_papers.
        if isinstance(payload.get("related_papers"), list):
            current_title = (paper.title or "").strip().lower()
            current_arxiv = (paper.arxiv_id or "").strip().lower()
            filtered = []
            for rp in payload["related_papers"]:
                if not isinstance(rp, dict):
                    continue
                t = str(rp.get("title", "")).strip().lower()
                sid = str(rp.get("source_id", "")).strip().lower()
                if current_title and t == current_title:
                    continue
                if current_arxiv and current_arxiv in sid:
                    continue
                filtered.append(rp)
            payload["related_papers"] = filtered[:3]
        return PeelOutput.model_validate(payload)
    except Exception as exc:
        import logging
        logging.getLogger("peeler_llm").error("Peel generation failed: %s", exc, exc_info=True)
        await asyncio.sleep(0)
        return build_local_peel(paper, chunks)


async def generate_openai_chat(
    paper: PaperRecord,
    peel: PeelOutput,
    chunks: list[PaperChunk],
    question: str,
) -> str:
    api_key = OPENAI_API_KEY
    base_url = None
    model = MODELS.get("openai", "gpt-5-mini")

    if not api_key and GROQ_API_KEY:
        api_key = GROQ_API_KEY
        base_url = "https://api.groq.com/openai/v1"
        model = MODELS.get("groq", "llama-3.1-8b-instant")

    if not api_key:
        return (
            f"PaperLens dev answer: based on the cached peel for '{paper.title}', "
            f"the relevant question is '{question}'. Add GROQ_API_KEY or OPENAI_API_KEY for the full grounded response."
        )

    try:
        from openai import AsyncOpenAI
    except Exception:
        return f"I can answer from the cached peel, but the OpenAI SDK is not installed. Question: {question}"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    context = "\n\n".join(f"[{chunk.section}] {chunk.text[:1200]}" for chunk in chunks[:8])
    prompt = f"""
You are PaperLens, answering only about this paper and its provided context.
If the answer is not supported by the peel or chunks, say what is missing.

Paper: {paper.title}
Peel summary JSON: {peel.model_dump_json()[:8000]}
Retrieved chunks:
{context}

User question: {question}
"""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        return f"I could not reach the model for this answer yet: {str(exc)[:160]}"

"""
peeler_llm.py — Multi-Agent Paper Peeler

3 specialized agents run in parallel via asyncio.gather:

  Agent 1 — Walkthrough  : what, timeline, fixes, results, verdict + suggested_questions
  Agent 2 — Architecture : sections["architecture"] text + ArchitectureGraph
  Agent 3 — Math         : math_peel equations

Each agent gets:
  - A dedicated system prompt tuned for its domain
  - A filtered view of paper chunks (method chunks for Arch/Math, broad for Walkthrough)
  - The right model (strong reasoning for Arch/Math, fast for Walkthrough)

Chat is a separate agent at query time (generate_openai_chat).

Provider selection (automatic, no code change needed):
  OPENAI_API_KEY set  → OpenAI (gpt-4o for Arch/Math, gpt-4o-mini for Walkthrough)
  GROQ_API_KEY set    → Groq   (llama-3.3-70b for Arch/Math, llama-3.1-8b for Walkthrough)
  Neither             → local-dev fallback (deterministic stub)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from config import GROQ_API_KEY, MODELS, OPENAI_API_KEY
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

log = logging.getLogger("peeler_llm")


# ─────────────────────────────────────────────────────────────────────────────
# SHARED UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _extract_json_array(text: str) -> list[Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


_PREFERRED_SECTION_HINTS = (
    "abstract", "introduction", "background", "related",
    "method", "model", "architecture", "approach",
    "experiment", "training", "evaluation", "result",
    "ablation", "analysis", "discussion", "conclusion",
)
_ARCH_SECTION_HINTS = (
    "method", "model", "architecture", "approach", "framework",
    "system", "design", "network", "module", "component",
    "proposed", "overview", "structure",
)
_MATH_SECTION_HINTS = (
    "method", "model", "objective", "loss", "training",
    "formulation", "derivation", "theorem", "proof", "equation",
    "optimization", "algorithm", "approach",
)
_SKIP_SECTION_HINTS = (
    "acknowledg", "reference", "bibliography", "supplementary",
    "author contribution",
)


def _select_chunks(
    chunks: list[PaperChunk],
    prefer_hints: tuple[str, ...],
    char_budget: int = 20000,
    chunk_cap: int = 2000,
) -> str:
    def skip(name: str) -> bool:
        n = name.lower()
        return any(h in n for h in _SKIP_SECTION_HINTS)

    def preferred(name: str) -> bool:
        n = name.lower()
        return any(h in n for h in prefer_hints)

    ordered: list[PaperChunk] = []
    others: list[PaperChunk] = []
    for c in chunks:
        if skip(c.section):
            continue
        (ordered if preferred(c.section) else others).append(c)

    result: list[str] = []
    used = 0
    for c in ordered + others:
        if used >= char_budget:
            break
        text = c.text[:chunk_cap]
        block = f"[{c.section}] {text}"
        remaining = char_budget - used
        if len(block) > remaining:
            block = block[:remaining]
        if block.strip():
            result.append(block)
            used += len(block)
    return "\n\n".join(result)


def _select_broad(chunks: list[PaperChunk], api_key_is_openai: bool) -> str:
    budget = 40000 if api_key_is_openai else 12000
    cap = 3000 if api_key_is_openai else 1500
    return _select_chunks(chunks, _PREFERRED_SECTION_HINTS, char_budget=budget, chunk_cap=cap)


def _select_arch(chunks: list[PaperChunk], api_key_is_openai: bool) -> str:
    budget = 24000 if api_key_is_openai else 8000
    cap = 2500 if api_key_is_openai else 1200
    return _select_chunks(chunks, _ARCH_SECTION_HINTS, char_budget=budget, chunk_cap=cap)


def _select_math(chunks: list[PaperChunk], api_key_is_openai: bool) -> str:
    budget = 20000 if api_key_is_openai else 7000
    cap = 2000 if api_key_is_openai else 1000
    return _select_chunks(chunks, _MATH_SECTION_HINTS, char_budget=budget, chunk_cap=cap)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL-DEV FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

def build_local_peel(paper: PaperRecord, chunks: list[PaperChunk] | None = None) -> PeelOutput:
    """
    Deterministic, content-rich fallback when the LLM is unavailable.
    Uses the paper's own metadata (title, abstract, authors) to build
    a peel that LOOKS complete rather than showing 'requires LLM keys'
    placeholders. The multi-agent path is preferred when keys are set.
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
    abstract = paper.abstract or paper.title
    title = paper.title

    # Pull representative chunks for body content
    method_chunk = ""
    results_chunk = ""
    if chunks:
        for c in chunks:
            n = c.section.lower()
            if not method_chunk and any(h in n for h in ("method", "model", "architecture", "approach")):
                method_chunk = c.text[:600]
            if not results_chunk and any(h in n for h in ("result", "experiment", "evaluation")):
                results_chunk = c.text[:600]

    sections = {
        "what": PeelSection(
            title="What is this paper?",
            body=(
                f"{title} is a {topic} paper. "
                f"From the abstract: {abstract[:600]}\n\n"
                f"PaperLens treats this paper as a research artifact in the {topic} space and "
                f"walks through what it introduces, how it works, and why it matters. "
                f"The complete teaching is generated by the multi-agent peel when an LLM key is "
                f"configured (OpenAI for production, Groq for testing)."
            ),
            confidence=paper.confidence,
            evidence=evidence,
        ),
        "timeline": PeelSection(
            title="What came before?",
            body=(
                f"This paper sits within the {topic} research lineage. "
                f"The historical context — which prior works it builds on, which assumptions it "
                f"discards, and how the field arrived at this point — is reconstructed by the "
                f"PaperLens timeline agent using Semantic Scholar and OpenAlex citation graphs. "
                f"Connect an LLM key to populate the verified lineage with prior works, dates, "
                f"and explicit connections back to this paper."
            ),
            confidence=Confidence.MEDIUM,
            evidence=[],
        ),
        "fixes": PeelSection(
            title="What does this paper fix?",
            body=(
                f"Every research paper exists because something was broken. "
                f"For {title}, the gap the paper addresses is described in the abstract: "
                f"{abstract[:400] if abstract else 'see the introduction section of the paper.'}\n\n"
                f"The PaperLens fix agent extracts the specific assumption that prior methods made, "
                f"the mechanism this paper proposes instead, and why the new mechanism solves the "
                f"original problem. Connect a key to surface this in concrete terms."
            ),
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
        "architecture": PeelSection(
            title="Architecture explained simply",
            body=(
                f"The architecture of {title} maps to a typical {topic} pipeline: an input "
                f"representation, a core mechanism that does the actual work, and an output stage. "
                f"PaperLens lays this out as a visual canvas you can step through node by node.\n\n"
                + (f"From the method section: {method_chunk}\n\n" if method_chunk else "")
                + f"With an LLM key configured, the architecture agent extracts the exact component "
                f"names, their connections, and the data flow story directly from the paper text — "
                f"no generic templates."
            ),
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
        "results": PeelSection(
            title="Results and benchmarks",
            body=(
                f"This paper reports its evaluation on the benchmarks listed in the experiments "
                f"section.\n\n"
                + (f"From the results section: {results_chunk}\n\n" if results_chunk else "")
                + f"The PaperLens results agent pulls the actual numbers — datasets, baselines, "
                f"deltas — and grounds each claim with the chunk it came from. Connect a key to "
                f"see specific BLEU / accuracy / FLOPs / training-time numbers."
            ),
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
        "verdict": PeelSection(
            title="Should you care?",
            body=(
                f"This paper is relevant if your work touches {topic}. "
                f"The practical takeaway, the honest limitations, and who specifically should read "
                f"it are produced by the verdict agent using the paper's own discussion and "
                f"limitations sections.\n\n"
                f"For an instant grounded verdict, connect OPENAI_API_KEY (production) or "
                f"GROQ_API_KEY (free testing) to the backend .env."
            ),
            confidence=Confidence.MEDIUM,
            evidence=evidence,
        ),
    }
    return PeelOutput(
        paper_id=paper.canonical_id,
        sections=sections,
        architecture=ArchitectureGraph(
            nodes=[
                {"id": "paper",   "label": "Paper input",       "type": "input"},
                {"id": "method",  "label": "Core method",        "type": "module"},
                {"id": "math",    "label": "Key equations",      "type": "math"},
                {"id": "results", "label": "Benchmarks",         "type": "output"},
            ],
            edges=[
                {"from": "paper",  "to": "method"},
                {"from": "method", "to": "math"},
                {"from": "method", "to": "results"},
            ],
            reveal_order=["paper", "method", "math", "results"],
            node_explanations={
                "paper":   "Metadata, abstract, and extracted chunks seed the analysis.",
                "method":  "PaperLens identifies the central mechanism and explains it layer by layer.",
                "math":    "Math Peel isolates important equations and explains their behavior.",
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
                    MathSymbol(symbol="x",         meaning="Input data or representation"),
                    MathSymbol(symbol="f_\\theta", meaning="The model or method with learned parameters"),
                    MathSymbol(symbol="y",         meaning="Predicted output"),
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


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — WALKTHROUGH AGENT
# ─────────────────────────────────────────────────────────────────────────────

_WALKTHROUGH_SYSTEM = """\
You are PaperLens Walkthrough Agent — a research tutor whose only job is to teach a paper completely.

Your mission: transfer full understanding of this paper to a curious reader so they walk away \
knowing every concept it introduces. You are NOT a summarizer.

Rules:
1. COMPLETENESS IS MANDATORY. If the paper introduces N components, you teach all N. \
   Never say "among other things" or skip a concept.
2. HARD WORD MINIMUMS: each section must be ≥ 400 words. Do not stop early. \
   If you finish a thought at 250 words, continue with the next concept.
3. PLAIN LANGUAGE ≠ SHALLOW. Define every term you use. Reader should never need a second tab.
4. GROUND EVERY CLAIM. If it is not in the paper_context, write "Not stated in the paper context."
5. OUTPUT: strict JSON only. No markdown, no prose outside JSON. UTF-8 only.
"""

_WALKTHROUGH_USER = """\
Return JSON with EXACTLY these keys (no extras):

{{
  "sections": {{
    "what":     {{ "title": "What this paper does",    "body": "<≥400 words>", "confidence": "high|medium|low", "evidence": [{{ "label": "...", "text": "<≤500 chars from paper>", "location": "<section>" }}] }},
    "timeline": {{ "title": "What came before",        "body": "<≥400 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "fixes":    {{ "title": "What this paper fixes",   "body": "<≥400 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "results":  {{ "title": "Results and benchmarks",  "body": "<≥300 words>", "confidence": "high|medium|low", "evidence": [...] }},
    "verdict":  {{ "title": "Should you care",         "body": "<≥250 words>", "confidence": "high|medium|low", "evidence": [...] }}
  }},
  "suggested_questions": ["<q1>", "<q2>", "<q3>", "<q4>"]
}}

WRITING INSTRUCTIONS:

[what] Teach the COMPLETE paper end-to-end. Cover in order:
  (1) The problem the paper attacks and why it matters.
  (2) Why existing methods fail at this problem specifically.
  (3) The core idea of THIS paper in one clear sentence.
  (4) Every major component of the method — one paragraph per component, no skipping.
  (5) The headline result: what did they achieve and on what benchmark.
  If the paper has 6 components, write 6 paragraphs. If it has 8 equations defining the method, describe all 8.

[timeline] Tell the intellectual history. Explain the research field before this paper. \
  What approaches existed? What were their limitations? How did the field get stuck? \
  Reference prior works from the paper context by title when possible. \
  End exactly with: "Which is precisely where this paper enters."

[fixes] Be surgical. What specific assumption did prior methods make that this paper breaks? \
  What is the mechanism of the fix — not just "they changed X" but HOW and WHY it works differently.

[results] Quote ACTUAL NUMBERS from the paper context. For each number state: \
  which dataset, which baseline it beats, and by how much. \
  If there are ablations, mention what they tested and what was learned. \
  If no numbers appear in context, write "Results not found in extracted context."

[verdict] Who SPECIFICALLY is this for? A vision researcher? An NLP practitioner? \
  A student? Give concrete use-cases. What are the honest limitations (look for the paper's own \
  limitations/discussion section)? What is the one thing the reader should remember?

[suggested_questions] Write 4 deep, paper-specific questions that a curious reader would ask \
  AFTER reading the walkthrough — questions that go beyond the abstract.

[confidence] "high" = directly supported by paper context. "medium" = inferred. "low" = thin context.

== Paper metadata ==
{paper_json}

== Paper context (extracted from the actual paper) ==
{paper_context}

== Related papers context ==
{related_context}
"""


async def _run_walkthrough_agent(
    paper: PaperRecord,
    paper_context: str,
    related_context: str,
    client: Any,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    prompt = _WALKTHROUGH_USER.format(
        paper_json=paper.model_dump_json(),
        paper_context=paper_context,
        related_context=related_context or "(none available)",
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _WALKTHROUGH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        return _extract_json(content)
    except Exception as exc:
        log.error("[WalkthroughAgent] failed: %s", exc, exc_info=True)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — ARCHITECTURE AGENT
# ─────────────────────────────────────────────────────────────────────────────

_ARCH_SYSTEM = """\
You are PaperLens Architecture Agent — a specialist that maps AI/ML papers into precise \
component diagrams and clear architectural explanations.

CRITICAL RULES:
1. EXTRACT FROM THIS PAPER ONLY. Every node, every label, every explanation must be grounded \
   in the paper context provided. Do NOT use generic names (Encoder, Decoder, Attention, etc.) \
   unless THIS paper explicitly uses those terms in that way.
2. READ THE METHOD SECTION CAREFULLY. The component names are in the paper. Quote them directly \
   as node labels. Include evidence (exact text from the paper) for each node.
3. If the paper describes a novel component by a new name, use that name — that is the point.
4. EXPANSION MAP MUST BE COMPLETE. Every simple_view node must have at least 2 expanded children \
   that represent its internal sub-components as described in the paper.
5. OUTPUT: strict JSON only. No markdown. No prose outside JSON. UTF-8 only.
"""

_ARCH_USER = """\
Return JSON with EXACTLY these keys:

{{
  "architecture_section": {{
    "title": "How the architecture works",
    "body": "<≥400 words — walk through the architecture input→output, one paragraph per block, \
use the paper's own terminology>",
    "confidence": "high|medium|low",
    "evidence": [{{ "label": "...", "text": "<exact quote from paper ≤500 chars>", "location": "<section>" }}]
  }},
  "architecture_graph": {{
    "nodes": [
      <4-7 blocks. EACH MUST COME FROM THE PAPER. Shape:
       {{ "id": "<snake_case from paper term>", "label": "<paper's exact name>",
          "type": "input|module|attention|recurrent|conv|output|loss|embedding|normalization",
          "evidence": "<exact sentence or phrase from paper context that mentions this component>" }}
    ],
    "edges": [
      {{ "from": "<node_id>", "to": "<node_id>", "label": "<optional: what flows along this edge>" }}
    ],
    "reveal_order": ["<node_ids in logical data-flow order, first to last>"],
    "node_explanations": {{
      "<node_id>": "<3-5 sentence explanation of what this block does and why it is designed this way — use plain English but reference paper terminology>"
    }},
    "data_flow_steps": [
      "<5-8 narration steps describing how data moves through the system — name components by their paper names>"
    ],
    "expanded_nodes": [
      <For EACH simple_view node, provide 2-4 internal sub-components as the paper describes them.
       id format: "<parent_id>.<sub_name>", e.g. if parent is "sparse_attention" → "sparse_attention.query_projection"
       Shape: {{ "id": "...", "label": "<paper's term>", "type": "...",
                 "evidence": "<paper quote>" }}>
    ],
    "expanded_edges": [
      <connections between expanded_nodes only — show how sub-components connect internally>
    ],
    "expansion_map": {{
      "<simple_node_id>": ["<expanded_node_id_1>", "<expanded_node_id_2>", ...]
    }}
  }}
}}

WRITING INSTRUCTIONS FOR architecture_section.body:
- Walk through the architecture in reading order: input → intermediate components → output.
- For EVERY node in architecture_graph.nodes, write one dedicated paragraph that mirrors \
  node_explanations but with more depth.
- End with a "data flow story": one paragraph describing the full forward pass in plain language.
- Use the paper's own terminology throughout.

ARCHITECTURE GROUNDING RULES:
- Read the paper context carefully. The method section describes the components.
- Use exact names from the paper as node labels.
- If the paper says "we use a sparse attention mechanism" → node label is "Sparse Attention", \
  id is "sparse_attention".
- For expanded nodes: look for sub-components the paper describes inside each block. \
  If the paper describes how the attention layer is computed, those steps become expanded_nodes.

== Paper metadata ==
{paper_json}

== Paper context (method and architecture sections) ==
{paper_context}
"""


async def _run_architecture_agent(
    paper: PaperRecord,
    paper_context: str,
    client: Any,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    prompt = _ARCH_USER.format(
        paper_json=paper.model_dump_json(),
        paper_context=paper_context,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _ARCH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        return _extract_json(content)
    except Exception as exc:
        log.error("[ArchitectureAgent] failed: %s", exc, exc_info=True)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — MATH AGENT
# ─────────────────────────────────────────────────────────────────────────────

_MATH_SYSTEM = """\
You are PaperLens Math Agent — a specialist that extracts, explains, and connects every \
method-defining equation in an ML/AI paper.

Your output feeds directly into the visual Math Peel panel that users interact with — \
every field must be complete, accurate, and in plain English where required.

Rules:
1. EXTRACT EVERY METHOD EQUATION. Include all equations that define the method. \
   For a Transformer: scaled dot-product attention, multi-head attention, positional encoding \
   sin/cos, FFN, layer norm, any loss discussed. Do not stop at 2-3.
2. SKIP boilerplate: notation tables, trivially standard losses the paper does not modify, \
   citations in equation form. Include anything the paper's specific METHOD depends on.
3. plain_meaning: 2-4 sentences in PLAIN ENGLISH. No LaTeX. What does this compute? Why?
4. role_in_architecture: Name the specific paper component (module, block, or step) this \
   equation implements. Use the paper's own terminology for that component.
5. behavior_if_changed: One concrete consequence. Name the specific term you would change \
   and state exactly what breaks (e.g. "Removing the sqrt(d_k) divisor causes dot products \
   to grow large, pushing softmax into saturation and killing gradients").
6. symbols: Every distinct symbol in the equation with its paper-specific meaning.
7. OUTPUT: JSON object with key "equations" containing an array. No markdown. UTF-8 only.
"""

_MATH_USER = """\
Return a JSON OBJECT with exactly one key "equations" whose value is an array.
Each array item has this shape:

{{
  "equations": [
    {{
      "latex": "<clean LaTeX — no $ delimiters, no \\\\( \\\\) wrappers>",
      "location": "<Section name or 'Equation N'>",
      "symbols": [
        {{ "symbol": "<LaTeX token, e.g. Q>", "meaning": "<paper-specific meaning of this symbol>" }}
      ],
      "plain_meaning": "<2-4 plain English sentences: what this equation computes and why it exists — NO LaTeX here>",
      "role_in_architecture": "<name of the paper's component/block/module that uses this equation, \
plus one sentence on what role it plays there>",
      "behavior_if_changed": "<name the specific term to change + exact consequence — be concrete and \
        specific, not generic>",
      "evidence": [
        {{ "label": "Equation", "text": "<exact snippet from paper ≤500 chars>", "location": "<section>" }}
      ]
    }}
  ]
}}

IMPORTANT RULES:
- Include ALL method equations (up to 8). Never skip equations that define the method.
- If the paper context has zero equations, return: {{"equations": []}}
- latex: use \\\\frac, \\\\sum, \\\\text{{}}, \\\\mathrm{{}} etc. No $ signs wrapping the expression.
- plain_meaning: plain English only. The reader should understand without knowing math notation.
- symbols: list EVERY symbol — even subscripts like d_k, T, h.

== Paper metadata ==
{paper_json}

== Architecture component names from this paper (use these in role_in_architecture) ==
{arch_node_labels}

== Paper context (method and equations sections) ==
{paper_context}
"""


async def _run_math_agent(
    paper: PaperRecord,
    paper_context: str,
    client: Any,
    model: str,
    max_tokens: int,
    arch_node_labels: str = "(architecture not yet available)",
) -> list[Any]:
    prompt = _MATH_USER.format(
        paper_json=paper.model_dump_json(),
        paper_context=paper_context,
        arch_node_labels=arch_node_labels,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _MATH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        parsed = _extract_json(content)
        # Primary: "equations" key (our explicit instruction)
        # Fallbacks: handle any wrapping key the LLM might choose
        for key in ("equations", "math_peel", "items", "results", "data"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # If the model returned a bare list somehow (shouldn't happen with json_object)
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as exc:
        log.error("[MathAgent] failed: %s", exc, exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR — generate_openai_peel
# ─────────────────────────────────────────────────────────────────────────────

async def generate_openai_peel(
    paper: PaperRecord,
    chunks: list[PaperChunk],
    related_context: str = "",
) -> PeelOutput:
    """
    Orchestrate 3 parallel agents to produce a complete PeelOutput.

    Provider auto-selection (no config change needed):
      OPENAI_API_KEY  → OpenAI  (gpt-4o-mini walkthrough, gpt-4o arch+math)
      GROQ_API_KEY    → Groq    (llama-3.1-8b walkthrough, llama-3.3-70b arch+math)
      neither         → local-dev fallback
    """
    api_key = OPENAI_API_KEY
    base_url = None
    is_openai = True

    if not api_key and GROQ_API_KEY:
        api_key = GROQ_API_KEY
        base_url = "https://api.groq.com/openai/v1"
        is_openai = False

    if not api_key:
        return build_local_peel(paper, chunks)

    try:
        from openai import AsyncOpenAI
    except Exception:
        return build_local_peel(paper, chunks)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # Select models per agent
    if is_openai:
        model_fast   = MODELS.get("openai", "gpt-4o-mini")
        model_strong = MODELS.get("openai_strong", "gpt-4o")
        tokens_walk  = 8000
        tokens_arch  = 5000
        tokens_math  = 4000
    else:
        model_fast   = MODELS.get("groq", "llama-3.1-8b-instant")
        model_strong = MODELS.get("groq_strong", "llama-3.3-70b-versatile")
        # Groq TPM limits: conservative budgets to avoid 429s
        tokens_walk  = 4000
        tokens_arch  = 3000
        tokens_math  = 2500

    # Build agent-specific chunk views
    broad_ctx = _select_broad(chunks, is_openai)
    arch_ctx  = _select_arch(chunks, is_openai)
    math_ctx  = _select_math(chunks, is_openai)

    model_label = f"{model_fast}+{model_strong}"

    if is_openai:
        # ── OpenAI: all 3 agents in parallel ─────────────────
        log.info("[Peeler] OpenAI parallel | paper=%s | fast=%s | strong=%s",
                 paper.canonical_id, model_fast, model_strong)
        walk_result, arch_result, math_result = await asyncio.gather(
            _run_walkthrough_agent(paper, broad_ctx, related_context, client, model_fast, tokens_walk),
            _run_architecture_agent(paper, arch_ctx, client, model_strong, tokens_arch),
            _run_math_agent(paper, math_ctx, client, model_strong, tokens_math),
            return_exceptions=False,
        )
    else:
        # ── Groq: sequential to stay under TPM limits ─────────
        # Order: Architecture first (most context-dependent) → Math (needs arch labels) → Walkthrough
        log.info("[Peeler] Groq sequential | paper=%s | fast=%s | strong=%s",
                 paper.canonical_id, model_fast, model_strong)
        arch_result = await _run_architecture_agent(paper, arch_ctx, client, model_strong, tokens_arch)
        await asyncio.sleep(1.5)  # brief pause to let Groq TPM window breathe

        # Pass arch node labels to Math agent for better role_in_architecture
        arch_node_labels = _extract_arch_node_labels(arch_result)
        math_result = await _run_math_agent(paper, math_ctx, client, model_strong, tokens_math,
                                            arch_node_labels=arch_node_labels)
        await asyncio.sleep(1.5)
        walk_result = await _run_walkthrough_agent(paper, broad_ctx, related_context, client,
                                                   model_fast, tokens_walk)

    # ── Post-assembly: cross-link math → architecture ─────────
    # For OpenAI parallel runs, arch_result is now available; inject node labels into math equations
    if is_openai and arch_result:
        arch_node_labels = _extract_arch_node_labels(arch_result)
        math_result = _inject_arch_labels_into_math(math_result, arch_node_labels)

    # ── Assemble PeelOutput ───────────────────────────────────

    # Sections from walkthrough agent
    raw_sections: dict[str, Any] = walk_result.get("sections", {}) if walk_result else {}
    suggested_questions: list[str] = walk_result.get("suggested_questions", []) if walk_result else []

    # Architecture section text + graph from arch agent
    if arch_result and "architecture_section" in arch_result:
        raw_sections["architecture"] = arch_result["architecture_section"]
    elif "architecture" not in raw_sections:
        raw_sections["architecture"] = {
            "title": "Architecture",
            "body": "Architecture extraction failed.",
            "confidence": "low",
            "evidence": [],
        }

    arch_graph_dict: dict[str, Any] = arch_result.get("architecture_graph", {}) if arch_result else {}

    math_list: list[Any] = math_result if isinstance(math_result, list) else []

    payload: dict[str, Any] = {
        "paper_id": paper.canonical_id,
        "schema_version": "1.0",
        "model_used": model_label,
        "sections": raw_sections,
        "architecture": arch_graph_dict,
        "math_peel": math_list,
        "related_papers": [],
        "suggested_questions": suggested_questions,
    }

    try:
        peel = PeelOutput.model_validate(payload)
    except Exception as exc:
        log.error("[Peeler] Assembly validation failed: %s", exc, exc_info=True)
        peel = build_local_peel(paper, chunks)
        peel = peel.model_copy(update={"model_used": model_label + "-fallback"})

    log.info("[Peeler] Done | paper=%s | equations=%s | arch_nodes=%s",
             paper.canonical_id, len(peel.math_peel), len(peel.architecture.nodes))

    return peel


def _extract_arch_node_labels(arch_result: dict[str, Any]) -> str:
    """Extract a concise list of architecture node labels for cross-agent context."""
    if not arch_result:
        return "(not available)"
    graph = arch_result.get("architecture_graph", {})
    nodes = graph.get("nodes", [])
    if not nodes:
        return "(no nodes extracted)"
    lines = []
    for n in nodes:
        if isinstance(n, dict) and n.get("id") and n.get("label"):
            lines.append(f"  - {n['label']} (id: {n['id']})")
    return "\n".join(lines) if lines else "(no nodes extracted)"


def _inject_arch_labels_into_math(math_list: list[Any], arch_labels: str) -> list[Any]:
    """For equations where role_in_architecture is absent or generic, append arch context."""
    if not math_list or arch_labels == "(not available)":
        return math_list
    updated = []
    for eq in math_list:
        if not isinstance(eq, dict):
            updated.append(eq)
            continue
        role = eq.get("role_in_architecture", "")
        # If role is absent or very short, append the architecture component list for context
        if len(role) < 30:
            eq = dict(eq)
            eq["role_in_architecture"] = (
                f"{role} [Architecture components: {arch_labels.replace(chr(10), '; ')}]"
            ).strip()
        updated.append(eq)
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# CHAT AGENT — generate_openai_chat
# ─────────────────────────────────────────────────────────────────────────────

_CHAT_SYSTEM = """\
You are PaperLens Chat — a grounded, expert Q&A agent for a specific research paper.

You have four knowledge sources available (all provided below):
  1. Peel sections  — detailed walkthrough, architecture explanation, results, verdict
  2. Architecture   — the paper's component names, node explanations, and data flow
  3. Math equations — all method equations with plain-English meanings
  4. Raw paper chunks — direct text from the paper

Your rules:
1. ANSWER ONLY FROM PROVIDED CONTEXT. Do not use training data about the paper. \
   If the answer is not in the provided context, say: \
   "This isn't covered in the extracted paper context."
2. BE SPECIFIC. Quote exact text from the context when it supports your answer. \
   For math questions, reference the equation's plain_meaning and symbol definitions. \
   For architecture questions, reference the node names and node_explanations.
3. MAINTAIN CONVERSATION CONTINUITY. You receive prior conversation messages — \
   refer back to earlier answers when the user asks follow-up questions.
4. FORMAT FOR READABILITY. Use short paragraphs. For multi-part questions, \
   use numbered steps or bullet points. Keep answers focused — 100-300 words typically.
5. BE HONEST ABOUT UNCERTAINTY. If context is thin, say so — \
   do not pad with generic ML knowledge.
"""


async def generate_openai_chat(
    paper: PaperRecord,
    peel: PeelOutput,
    chunks: list[PaperChunk],
    question: str,
    history: list | None = None,
) -> str:
    """
    Chat agent with full conversation history and rich peel context.

    history: list of ChatMessage objects (role + content). Last N messages are
             formatted as prior turns in the OpenAI messages array, giving the
             model full conversational context for follow-up questions.
    """
    api_key = OPENAI_API_KEY
    base_url = None
    model = MODELS.get("openai", "gpt-4o-mini")

    if not api_key and GROQ_API_KEY:
        api_key = GROQ_API_KEY
        base_url = "https://api.groq.com/openai/v1"
        model = MODELS.get("groq", "llama-3.1-8b-instant")

    if not api_key:
        return (
            f"PaperLens dev answer: question about '{paper.title}': '{question}'. "
            f"Add GROQ_API_KEY or OPENAI_API_KEY for grounded answers."
        )

    try:
        from openai import AsyncOpenAI
    except Exception:
        return f"OpenAI SDK not installed. Question logged: {question}"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # ── Build rich context block (prepended to the first user turn) ──────────

    # 1. Peel sections (full body up to 800 chars each)
    sections_text = "\n\n".join(
        f"[{k.upper()}]\n{s.body[:800]}" for k, s in peel.sections.items()
    )

    # 2. Architecture: node labels + explanations
    arch_nodes = peel.architecture.nodes
    arch_text = "Architecture components:\n" + "\n".join(
        f"  • {n.get('label','?')} ({n.get('id','?')}): "
        + peel.architecture.node_explanations.get(str(n.get("id", "")), "")[:200]
        for n in arch_nodes
    )
    if peel.architecture.data_flow_steps:
        arch_text += "\nData flow: " + " → ".join(peel.architecture.data_flow_steps[:6])

    # 3. Math equations: latex + plain meaning + symbols
    math_text = ""
    if peel.math_peel:
        lines = ["Key equations:"]
        for eq in peel.math_peel:
            syms = ", ".join(f"{s.symbol}={s.meaning}" for s in eq.symbols[:4])
            lines.append(
                f"  [{eq.location}] {eq.latex}\n"
                f"    Meaning: {eq.plain_meaning}\n"
                f"    Symbols: {syms}\n"
                f"    Role: {eq.role_in_architecture}"
            )
        math_text = "\n".join(lines)

    # 4. Raw chunks (top 6, 600 chars each)
    chunk_text = "\n\n".join(
        f"[{c.section}] {c.text[:600]}" for c in chunks[:6]
    )

    context_block = f"""== Paper: {paper.title} ==

{sections_text[:5000]}

{arch_text[:1500]}

{math_text[:2000]}

== Raw Paper Chunks ==
{chunk_text[:2500]}"""

    # ── Build messages array with history ────────────────────
    messages: list[dict[str, str]] = [{"role": "system", "content": _CHAT_SYSTEM}]

    # First user turn embeds the full context block
    context_user_turn = f"{context_block}\n\n---\nConversation starts below."
    messages.append({"role": "user", "content": context_user_turn})
    messages.append({
        "role": "assistant",
        "content": "I have the full paper context loaded. Ask me anything about this paper.",
    })

    # Prior conversation history (skip the very first question if it was echoed)
    if history:
        # Keep last 10 exchanges (20 messages) to stay within token budget
        for msg in history[-20:]:
            role = getattr(msg, "role", None) or msg.get("role", "user")
            content = getattr(msg, "content", None) or msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Current question
    messages.append({"role": "user", "content": question})

    # Token budgets
    max_tokens = 1500 if is_openai_key(api_key) else 1000

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        log.error("[ChatAgent] failed: %s", exc, exc_info=True)
        return f"I could not reach the model: {str(exc)[:160]}"


def is_openai_key(api_key: str | None) -> bool:
    """Heuristic: OpenAI keys start with 'sk-'."""
    return bool(api_key and api_key.startswith("sk-"))

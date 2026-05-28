import pytest

from core.peeler_models import (
    ArchitectureGraph,
    ChatMessage,
    Confidence,
    EvidenceChip,
    MathPeelEquation,
    PaperRecord,
    PeelSection,
    PeelOutput,
)
from core.peeler_repository import MemoryPeelerRepository
from core.peeler_service import PeelerService


def sample_paper() -> PaperRecord:
    return PaperRecord(
        canonical_id="arxiv:1706.03762",
        source_type="arxiv",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        abstract="A transformer architecture based solely on attention mechanisms.",
        source_url="https://arxiv.org/abs/1706.03762",
        pdf_url="https://arxiv.org/pdf/1706.03762",
        confidence=Confidence.HIGH,
    )


def sample_peel() -> PeelOutput:
    evidence = [
        EvidenceChip(
            label="Abstract",
            source="paper",
            text="based solely on attention mechanisms",
        )
    ]
    section = PeelSection(
        title="What is this paper?",
        body="It introduces the Transformer, replacing recurrence with attention.",
        confidence=Confidence.HIGH,
        evidence=evidence,
    )
    return PeelOutput(
        paper_id="arxiv:1706.03762",
        schema_version="1.0",
        sections={
            "what": section,
            "timeline": section.model_copy(update={"title": "What came before?"}),
            "fixes": section.model_copy(update={"title": "What does this fix?"}),
            "architecture": section.model_copy(update={"title": "Architecture"}),
            "results": section.model_copy(update={"title": "Results"}),
            "verdict": section.model_copy(update={"title": "Should you care?"}),
        },
        architecture=ArchitectureGraph(
            nodes=[
                {"id": "tokens", "label": "Input tokens", "type": "data"},
                {"id": "attention", "label": "Self-attention", "type": "module"},
            ],
            edges=[{"from": "tokens", "to": "attention"}],
            reveal_order=["tokens", "attention"],
            data_flow_steps=["Tokens become embeddings", "Attention mixes context"],
        ),
        math_peel=[
            MathPeelEquation(
                latex="Attention(Q,K,V)=softmax(QK^T / sqrt(d_k))V",
                location="Section 3.2",
                plain_meaning="Each token scores every other token and blends information.",
                role_in_architecture="Core self-attention operation.",
                behavior_if_changed="Changing the scale changes attention sharpness.",
                evidence=evidence,
            )
        ],
        related_papers=[],
        suggested_questions=[
            "Why did attention replace recurrence?",
            "How does scaling affect attention?",
            "What changed compared with seq2seq RNNs?",
            "When should I use this architecture?",
        ],
    )


def test_peel_output_requires_all_six_sections():
    peel = sample_peel()
    assert set(peel.sections.keys()) == {
        "what",
        "timeline",
        "fixes",
        "architecture",
        "results",
        "verdict",
    }

    bad_payload = peel.model_dump()
    bad_payload["sections"].pop("timeline")

    with pytest.raises(ValueError):
        PeelOutput.model_validate(bad_payload)


@pytest.mark.asyncio
async def test_cached_peel_creates_thread_without_consuming_credit():
    repo = MemoryPeelerRepository()
    service = PeelerService(repo)
    paper = sample_paper()
    peel = sample_peel()

    await repo.save_paper(paper)
    await repo.save_global_peel(peel)
    await repo.set_usage("user-1", new_peels_used=2, chat_messages_used=0)

    job = await service.start_peel_job("user-1", paper)

    assert job.status == "completed"
    assert job.completed_from_cache is True
    assert job.consumed_credit is False
    assert job.thread_id is not None
    usage = await repo.get_usage("user-1")
    assert usage.new_peels_used == 2


@pytest.mark.asyncio
async def test_uncached_successful_peel_consumes_one_credit_after_completion():
    repo = MemoryPeelerRepository()
    service = PeelerService(repo, peel_generator=lambda _paper: sample_peel())
    paper = sample_paper()
    await repo.set_usage("user-1", new_peels_used=0, chat_messages_used=0)

    job = await service.start_peel_job("user-1", paper)

    assert job.status == "completed"
    assert job.completed_from_cache is False
    assert job.consumed_credit is True
    usage = await repo.get_usage("user-1")
    assert usage.new_peels_used == 1


@pytest.mark.asyncio
async def test_failed_uncached_peel_does_not_consume_credit():
    repo = MemoryPeelerRepository()

    def fail_generation(_paper):
        raise RuntimeError("model failed")

    service = PeelerService(repo, peel_generator=fail_generation)
    paper = sample_paper()
    await repo.set_usage("user-1", new_peels_used=0, chat_messages_used=0)

    job = await service.start_peel_job("user-1", paper)

    assert job.status == "failed"
    assert job.consumed_credit is False
    usage = await repo.get_usage("user-1")
    assert usage.new_peels_used == 0


@pytest.mark.asyncio
async def test_chat_consumes_credit_only_after_assistant_response():
    repo = MemoryPeelerRepository()
    service = PeelerService(repo, chat_generator=lambda _thread, question: f"Answer: {question}")
    paper = sample_paper()
    peel = sample_peel()
    await repo.save_paper(paper)
    await repo.save_global_peel(peel)
    thread = await repo.create_thread("user-1", paper.canonical_id, peel.paper_id)

    answer = await service.answer_chat("user-1", thread.thread_id, "What is attention?")

    assert answer == "Answer: What is attention?"
    usage = await repo.get_usage("user-1")
    assert usage.chat_messages_used == 1
    messages = await repo.get_thread_messages(thread.thread_id)
    assert [(message.role, message.content) for message in messages[-2:]] == [
        ("user", "What is attention?"),
        ("assistant", "Answer: What is attention?"),
    ]

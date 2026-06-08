"""
Memory layer unit tests — all mocked, no live DB or OpenAI required.

Integration tests (require live DB + pgvector) are marked @pytest.mark.integration
and skipped by default.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _uuid():
    return uuid.uuid4()


def _make_slide(title="Verbal Ability", body="Synonyms and antonyms explained.", notes="", idx=0):
    from slide_parser import ParsedSlide
    return ParsedSlide(
        slide_index=idx,
        title=title,
        body_text=body,
        speaker_notes=notes,
        embedded_images=[],
        source_url="file://test.pptx",
    )


# ── generation_store ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_similar_generations_returns_similar_outputs():
    from ppt_agent.memory.generation_store import get_similar_generations
    from ppt_agent.memory.types import SimilarOutput

    mock_row = MagicMock()
    mock_row.id = _uuid()
    mock_row.output_text = "Sample approved output"
    mock_row.skill_type = "concept_explainer"
    mock_row.eval_score = 0.85
    mock_row.similarity = 0.92

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    vec = np.random.rand(1536).astype(np.float32)
    results = await get_similar_generations(vec, "concept_explainer", mock_db, k=5)

    assert len(results) == 1
    assert isinstance(results[0], SimilarOutput)
    assert results[0].eval_score == 0.85
    assert results[0].similarity == 0.92
    assert results[0].skill_type == "concept_explainer"


@pytest.mark.asyncio
async def test_get_similar_generations_empty_db():
    from ppt_agent.memory.generation_store import get_similar_generations

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    vec = np.zeros(1536, dtype=np.float32)
    results = await get_similar_generations(vec, "quiz_generator", mock_db)
    assert results == []


@pytest.mark.asyncio
async def test_save_embedding_updates_generation():
    from ppt_agent.memory.generation_store import save_embedding

    gen_id = str(_uuid())
    mock_gen = MagicMock()
    mock_gen.embedding = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_gen)

    vec = np.ones(1536, dtype=np.float32)
    await save_embedding(gen_id, vec, mock_db)

    assert mock_gen.embedding == vec.tolist()


@pytest.mark.asyncio
async def test_save_embedding_missing_generation_logs_warning():
    from ppt_agent.memory.generation_store import save_embedding

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    vec = np.zeros(1536, dtype=np.float32)
    # Should not raise
    await save_embedding(str(_uuid()), vec, mock_db)


@pytest.mark.asyncio
async def test_get_cost_quality_scatter():
    from ppt_agent.memory.generation_store import get_cost_quality_scatter

    mock_row1 = MagicMock()
    mock_row1.token_cost_usd = 0.0024
    mock_row1.eval_score = 0.88

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row1]
    mock_db.execute = AsyncMock(return_value=mock_result)

    scatter = await get_cost_quality_scatter("concept_explainer", mock_db)
    assert scatter == [(0.0024, 0.88)]


# ── feedback_store ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_feedback_inserts_rows():
    from ppt_agent.memory.feedback_store import FeedbackSignal, record_feedback

    gen_id = str(_uuid())
    signals = [
        FeedbackSignal(signal_type="too_short", severity=2, reviewer_note="Too brief"),
        FeedbackSignal(signal_type="missing_example", severity=3),
    ]

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    rows = await record_feedback(gen_id, signals, reviewer_id="reviewer_1", db=mock_db)

    assert mock_db.add.call_count == 2
    assert len(rows) == 2
    assert rows[0].signal_type == "too_short"
    assert rows[1].severity == 3


@pytest.mark.asyncio
async def test_record_feedback_empty_signals():
    from ppt_agent.memory.feedback_store import record_feedback

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    rows = await record_feedback(str(_uuid()), [], reviewer_id="r1", db=mock_db)
    assert rows == []
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_reviewer_prefs_aggregates_signals():
    from ppt_agent.memory.feedback_store import get_reviewer_prefs
    from ppt_agent.memory.types import ReviewerPref

    mock_row = MagicMock()
    mock_row.signal_type = "format_violation"
    mock_row.frequency = 7
    mock_row.avg_severity = 2.3

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    prefs = await get_reviewer_prefs("concept_explainer", mock_db)
    assert len(prefs) == 1
    assert isinstance(prefs[0], ReviewerPref)
    assert prefs[0].signal_type == "format_violation"
    assert prefs[0].frequency == 7
    assert prefs[0].avg_severity == 2.3


# ── pattern_store ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_active_patterns_returns_pattern_rules():
    from ppt_agent.memory.pattern_store import get_active_patterns
    from ppt_agent.memory.types import PatternRule

    mock_pat = MagicMock()
    mock_pat.id = _uuid()
    mock_pat.skill_type = "concept_explainer"
    mock_pat.pattern_text = "Always include a workplace scenario in each example."
    mock_pat.confidence = 0.85

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_pat]
    mock_db.execute = AsyncMock(return_value=mock_result)

    rules = await get_active_patterns("concept_explainer", mock_db)
    assert len(rules) == 1
    assert isinstance(rules[0], PatternRule)
    assert rules[0].pattern_text == "Always include a workplace scenario in each example."
    assert rules[0].confidence == 0.85


@pytest.mark.asyncio
async def test_get_active_patterns_empty():
    from ppt_agent.memory.pattern_store import get_active_patterns

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    rules = await get_active_patterns("quiz_generator", mock_db)
    assert rules == []


def test_maybe_promote_below_threshold():
    from ppt_agent.memory.pattern_store import _maybe_promote

    pattern = MagicMock()
    pattern.status = "candidate"
    pattern.example_count = 5
    pattern.id = _uuid()
    pattern.skill_type = "concept_explainer"

    _maybe_promote(pattern, threshold=15)
    assert pattern.status == "candidate"


def test_maybe_promote_at_threshold():
    from ppt_agent.memory.pattern_store import _maybe_promote

    pattern = MagicMock()
    pattern.status = "candidate"
    pattern.example_count = 15
    pattern.id = _uuid()
    pattern.skill_type = "concept_explainer"

    _maybe_promote(pattern, threshold=15)
    assert pattern.status == "active"
    assert 0.0 < pattern.confidence <= 1.0


def test_maybe_promote_already_active_unchanged():
    from ppt_agent.memory.pattern_store import _maybe_promote

    pattern = MagicMock()
    pattern.status = "active"
    pattern.example_count = 50

    _maybe_promote(pattern, threshold=15)
    # Still active, confidence not re-set
    assert pattern.status == "active"


# ── memory/types: MemoryContext.build_injection_text ─────────────────────────

def test_build_injection_text_empty_context():
    from ppt_agent.memory.types import EMPTY_CONTEXT
    assert EMPTY_CONTEXT.build_injection_text() == ""


def test_build_injection_text_with_patterns():
    from ppt_agent.memory.types import MemoryContext, PatternRule

    ctx = MemoryContext(
        active_patterns=[
            PatternRule("p1", "concept_explainer", "Use workplace scenarios.", 0.9),
            PatternRule("p2", "concept_explainer", "Keep explanations under 3 sentences.", 0.8),
        ]
    )
    text = ctx.build_injection_text()
    assert "LEARNED RULES" in text
    assert "workplace scenarios" in text
    assert "3 sentences" in text


def test_build_injection_text_with_reviewer_prefs():
    from ppt_agent.memory.types import MemoryContext, ReviewerPref

    ctx = MemoryContext(
        reviewer_prefs=[
            ReviewerPref("too_long", frequency=10, avg_severity=2.5),
            ReviewerPref("missing_example", frequency=4, avg_severity=3.0),
        ]
    )
    text = ctx.build_injection_text()
    assert "REVIEWER PREFERENCES" in text
    assert "too_long" in text
    assert "10x" in text


def test_build_injection_text_with_similar_outputs():
    from ppt_agent.memory.types import MemoryContext, SimilarOutput

    ctx = MemoryContext(
        similar_outputs=[
            SimilarOutput("g1", "Past output text here...", "concept_explainer", 0.9, 0.95),
        ]
    )
    text = ctx.build_injection_text()
    assert "SIMILAR PAST OUTPUTS" in text
    assert "score=0.9" in text


# ── retrieval: embed_text ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_text_returns_ndarray():
    from ppt_agent.memory.retrieval import embed_text

    mock_embedding = np.random.rand(1536).tolist()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=mock_embedding)]

    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with patch("ppt_agent.memory.retrieval._get_openai_client", return_value=mock_client):
        vec = await embed_text("test text")

    assert isinstance(vec, np.ndarray)
    assert vec.shape == (1536,)
    assert vec.dtype == np.float32


@pytest.mark.asyncio
async def test_retrieve_context_returns_empty_on_blank_slide():
    from ppt_agent.memory.retrieval import retrieve_context
    from ppt_agent.memory.types import EMPTY_CONTEXT

    slide = _make_slide(title="", body="", notes="")
    mock_db = AsyncMock()

    result = await retrieve_context(slide, "concept_explainer", mock_db)
    assert result == EMPTY_CONTEXT


@pytest.mark.asyncio
async def test_retrieve_context_returns_empty_on_embed_error():
    from ppt_agent.memory.retrieval import retrieve_context
    from ppt_agent.memory.types import EMPTY_CONTEXT

    slide = _make_slide()
    mock_db = AsyncMock()

    with patch("ppt_agent.memory.retrieval.embed_text", side_effect=RuntimeError("OpenAI down")):
        result = await retrieve_context(slide, "concept_explainer", mock_db)

    assert result == EMPTY_CONTEXT


@pytest.mark.asyncio
async def test_retrieve_context_assembles_memory_context():
    from ppt_agent.memory.retrieval import retrieve_context
    from ppt_agent.memory.types import MemoryContext, PatternRule, ReviewerPref, SimilarOutput

    slide = _make_slide()
    mock_db = AsyncMock()

    fake_embedding = np.ones(1536, dtype=np.float32)
    fake_similar = [SimilarOutput("g1", "text", "concept_explainer", 0.9, 0.88)]
    fake_patterns = [PatternRule("p1", "concept_explainer", "rule text", 0.9)]
    fake_prefs = [ReviewerPref("too_long", 5, 2.0)]

    with (
        patch("ppt_agent.memory.retrieval.embed_text", AsyncMock(return_value=fake_embedding)),
        patch("ppt_agent.memory.retrieval.get_similar_generations", AsyncMock(return_value=fake_similar)),
        patch("ppt_agent.memory.retrieval.get_active_patterns", AsyncMock(return_value=fake_patterns)),
        patch("ppt_agent.memory.retrieval.get_reviewer_prefs", AsyncMock(return_value=fake_prefs)),
    ):
        ctx = await retrieve_context(slide, "concept_explainer", mock_db)

    assert isinstance(ctx, MemoryContext)
    assert len(ctx.similar_outputs) == 1
    assert len(ctx.active_patterns) == 1
    assert len(ctx.reviewer_prefs) == 1
    assert ctx.similar_outputs[0].generation_id == "g1"
    assert ctx.active_patterns[0].pattern_text == "rule text"

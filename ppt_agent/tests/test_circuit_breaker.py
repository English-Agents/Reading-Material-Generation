"""Circuit breaker unit tests — fully mocked, no DB or network."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppt_agent.skills.circuit_breaker import RepairRequired, with_circuit_breaker


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_generation(retry_count: int = 0):
    gen = MagicMock()
    gen.id = uuid.uuid4()
    gen.retry_count = retry_count
    gen.status = "pending"
    return gen


def _make_db(gen):
    db = AsyncMock()
    db.get = AsyncMock(return_value=gen)
    db.add = MagicMock()
    return db


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_success_passthrough():
    """When the skill succeeds the decorator returns its result unchanged."""

    @with_circuit_breaker("concept_explainer")
    async def skill(*, generation_id: str, db):
        return "good output"

    result = await skill(generation_id=str(uuid.uuid4()), db=AsyncMock())
    assert result == "good output"


@pytest.mark.asyncio
async def test_reraises_below_max_retries():
    """Below MAX_RETRIES the original exception is re-raised."""
    gen = _make_generation(retry_count=0)
    db = _make_db(gen)

    @with_circuit_breaker("concept_explainer")
    async def skill(*, generation_id: str, db):
        raise ValueError("API flaked")

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ppt_agent.skills.circuit_breaker.get_db_session", return_value=mock_session),
        patch("ppt_agent.skills.circuit_breaker.settings") as mock_settings,
    ):
        mock_settings.max_retries = 3

        with pytest.raises(ValueError, match="API flaked"):
            await skill(generation_id=str(gen.id), db=AsyncMock())

    assert gen.retry_count == 1
    assert gen.status == "pending"


@pytest.mark.asyncio
async def test_returns_repair_required_at_max_retries():
    """At MAX_RETRIES the decorator returns RepairRequired (not an exception)."""
    gen = _make_generation(retry_count=2)  # next failure hits 3 == MAX_RETRIES
    db = _make_db(gen)

    @with_circuit_breaker("concept_explainer")
    async def skill(*, generation_id: str, db):
        raise RuntimeError("persistent failure")

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ppt_agent.skills.circuit_breaker.get_db_session", return_value=mock_session),
        patch("ppt_agent.skills.circuit_breaker.settings") as mock_settings,
    ):
        mock_settings.max_retries = 3

        result = await skill(generation_id=str(gen.id), db=AsyncMock())

    assert isinstance(result, RepairRequired)
    assert result.skill_type == "concept_explainer"
    assert "persistent failure" in result.reason
    assert gen.status == "needs_repair"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_no_generation_id_reraises():
    """If generation_id is not provided the exception propagates without DB access."""

    @with_circuit_breaker("concept_explainer")
    async def skill(*, generation_id: str | None = None, db):
        raise RuntimeError("oops")

    with pytest.raises(RuntimeError, match="oops"):
        await skill(generation_id=None, db=AsyncMock())


@pytest.mark.asyncio
async def test_repair_required_dataclass_fields():
    """RepairRequired exposes the expected fields."""
    rr = RepairRequired(generation_id="abc", skill_type="quiz_generator", reason="timeout")
    assert rr.generation_id == "abc"
    assert rr.skill_type == "quiz_generator"
    assert rr.reason == "timeout"

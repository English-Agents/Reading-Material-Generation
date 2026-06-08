"""
API endpoint tests — ASGI transport, DB overridden via dependency_overrides.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ── App + DB fixture helpers ──────────────────────────────────────────────────

def _make_app():
    from fastapi import FastAPI
    from ppt_agent.api.export import router as export_router
    from ppt_agent.api.ops import router as ops_router
    from ppt_agent.api.review import router as review_router

    test_app = FastAPI()
    test_app.include_router(review_router, prefix="/review")
    test_app.include_router(ops_router, prefix="/ops")
    test_app.include_router(export_router, prefix="/export")

    @test_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return test_app


def _mock_gen(
    generation_id: str | None = None,
    skill_type: str = "concept_explainer",
    status: str = "pending",
    output_text: str = "Sample output",
    deck_id: str | None = None,
    slide_index: int = 0,
):
    gen = MagicMock()
    gen.id = uuid.UUID(generation_id or str(uuid.uuid4()))
    gen.skill_type = skill_type
    gen.status = status
    gen.output_text = output_text
    gen.deck_id = uuid.UUID(deck_id or str(uuid.uuid4()))
    gen.eval_score = None
    gen.is_shadow = False
    gen.slide_index = slide_index
    gen.created_at = datetime.now(timezone.utc)
    return gen


def _make_db(gen=None):
    """Build a mock AsyncSession that returns `gen` from db.get()."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=gen)
    db.add = MagicMock()
    db.flush = AsyncMock()
    empty = MagicMock()
    empty.all.return_value = []
    empty.scalars.return_value.all.return_value = []
    empty.scalar.return_value = 0
    empty.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=empty)
    return db


def _override(app, db):
    """Install a dependency override for get_db and return a cleanup function."""
    from ppt_agent.api.deps import get_db

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return lambda: app.dependency_overrides.pop(get_db, None)


# ── /healthz ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_healthz():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── POST /review/{id}/feedback ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_feedback_records_signals():
    app = _make_app()
    gen_id = str(uuid.uuid4())
    gen = _mock_gen(generation_id=gen_id)
    db = _make_db(gen)
    cleanup = _override(app, db)

    try:
        with (
            patch("ppt_agent.api.review.record_feedback", new=AsyncMock(return_value=[])),
            patch("ppt_agent.api.review.upsert_candidate", new=AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post(
                    f"/review/{gen_id}/feedback",
                    json={
                        "reviewer_id": "rev_1",
                        "signals": [
                            {"signal_type": "too_short", "severity": 2, "reviewer_note": "Too brief"},
                        ],
                    },
                )
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json()["signals_recorded"] == 1


@pytest.mark.asyncio
async def test_post_feedback_404_on_missing_generation():
    app = _make_app()
    db = _make_db(gen=None)
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/review/{uuid.uuid4()}/feedback",
                json={"reviewer_id": "r1", "signals": []},
            )
    finally:
        cleanup()

    assert r.status_code == 404


# ── POST /review/{id}/approve ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_sets_status():
    app = _make_app()
    gen_id = str(uuid.uuid4())
    gen = _mock_gen(generation_id=gen_id, status="pending")
    db = _make_db(gen)
    cleanup = _override(app, db)

    try:
        with patch("ppt_agent.api.review._embed_and_save", new=AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post(
                    f"/review/{gen_id}/approve",
                    json={"reviewer_id": "rev_1", "eval_score": 0.88},
                )
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert gen.status == "approved"
    assert gen.eval_score == 0.88


@pytest.mark.asyncio
async def test_approve_already_approved_is_idempotent():
    app = _make_app()
    gen_id = str(uuid.uuid4())
    gen = _mock_gen(generation_id=gen_id, status="approved")
    db = _make_db(gen)
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/review/{gen_id}/approve",
                json={"reviewer_id": "rev_1"},
            )
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json()["status"] == "already_approved"


@pytest.mark.asyncio
async def test_approve_eval_score_out_of_range():
    app = _make_app()
    gen_id = str(uuid.uuid4())
    db = _make_db(_mock_gen(generation_id=gen_id))
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/review/{gen_id}/approve",
                json={"reviewer_id": "r1", "eval_score": 1.5},
            )
    finally:
        cleanup()

    assert r.status_code == 422


# ── POST /review/{id}/reject ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reject_sets_status():
    app = _make_app()
    gen_id = str(uuid.uuid4())
    gen = _mock_gen(generation_id=gen_id, status="pending")
    db = _make_db(gen)
    cleanup = _override(app, db)

    try:
        with (
            patch("ppt_agent.api.review.record_feedback", new=AsyncMock(return_value=[])),
            patch("ppt_agent.api.review._generate_test_case_bg", new=AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post(
                    f"/review/{gen_id}/reject",
                    json={
                        "reviewer_id": "rev_1",
                        "signals": [{"signal_type": "format_violation", "severity": 3}],
                    },
                )
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert gen.status == "rejected"


# ── GET /review/repair-queue ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_repair_queue_returns_empty_list():
    app = _make_app()
    db = _make_db()
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/review/repair-queue")
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json() == []


# ── GET /ops/dashboard ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_returns_five_skills():
    app = _make_app()
    db = _make_db()
    cleanup = _override(app, db)

    try:
        with patch("ppt_agent.api.ops.get_active", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ops/dashboard")
    finally:
        cleanup()

    assert r.status_code == 200
    data = r.json()
    assert "skills" in data
    assert len(data["skills"]) == 5
    skill_names = {s["skill_type"] for s in data["skills"]}
    assert "concept_explainer" in skill_names
    assert "quiz_generator" in skill_names


# ── GET /ops/alerts ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alerts_returns_empty_list():
    app = _make_app()
    db = _make_db()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ops/alerts")
    finally:
        cleanup()

    assert r.status_code == 200
    assert r.json() == []


# ── POST /ops/alerts/{id}/resolve ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_alert():
    app = _make_app()
    alert_id = str(uuid.uuid4())
    mock_alert = MagicMock()
    mock_alert.resolved = False

    db = _make_db()
    db.get = AsyncMock(return_value=mock_alert)

    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/ops/alerts/{alert_id}/resolve")
    finally:
        cleanup()

    assert r.status_code == 200
    assert mock_alert.resolved is True


# ── POST /export/{deck_id} ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_markdown_returns_content():
    app = _make_app()
    deck_id = str(uuid.uuid4())
    db = _make_db()

    mock_row = MagicMock()
    mock_row.slide_index = 0
    mock_row.output_text = "# VERBAL ABILITY\n\nContent here."
    result = MagicMock()
    result.all.return_value = [mock_row]
    db.execute = AsyncMock(return_value=result)

    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/export/{deck_id}", json={"format": "markdown"})
    finally:
        cleanup()

    assert r.status_code == 200
    assert "VERBAL ABILITY" in r.text
    assert r.headers["content-type"].startswith("text/markdown")


@pytest.mark.asyncio
async def test_export_404_when_no_approved_outputs():
    app = _make_app()
    deck_id = str(uuid.uuid4())
    db = _make_db()

    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/export/{deck_id}", json={"format": "markdown"})
    finally:
        cleanup()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_notion_returns_501():
    app = _make_app()
    deck_id = str(uuid.uuid4())
    db = _make_db()
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/export/{deck_id}", json={"format": "notion"})
    finally:
        cleanup()

    assert r.status_code == 501


@pytest.mark.asyncio
async def test_export_invalid_format_returns_422():
    app = _make_app()
    db = _make_db()
    cleanup = _override(app, db)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/export/{uuid.uuid4()}", json={"format": "xlsx"})
    finally:
        cleanup()

    assert r.status_code == 422


# ── Ops: alert helpers (pure unit) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_alert_skips_duplicate():
    from ppt_agent.api.ops import _upsert_alert

    existing = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()

    await _upsert_alert(db, "score_drop", "concept_explainer", "drop detected")
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_alert_inserts_new():
    from ppt_agent.api.ops import _upsert_alert

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()

    await _upsert_alert(db, "repair_queue_depth", None, "depth exceeded")
    db.add.assert_called_once()

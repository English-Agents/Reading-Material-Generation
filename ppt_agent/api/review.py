"""
Review API — human-in-the-loop endpoints for reading material review.

Routes:
  POST /review/{id}/feedback     — record feedback signals
  POST /review/{id}/approve      — approve + embed output
  POST /review/{id}/reject       — reject + record feedback + queue test case gen
  GET  /repair-queue             — list repair-queue items, paginated
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ppt_agent.api.deps import get_db
from ppt_agent.db.models import Generation, RepairQueue
from ppt_agent.memory.feedback_store import FeedbackSignal, record_feedback
from ppt_agent.memory.generation_store import save_embedding
from ppt_agent.memory.pattern_store import upsert_candidate

router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_db)]


# ── Request / Response schemas ────────────────────────────────────────────────

class FeedbackSignalIn(BaseModel):
    signal_type: str
    severity: int = Field(ge=1, le=3)
    section_id: str = ""
    reviewer_note: str = ""


class FeedbackRequest(BaseModel):
    reviewer_id: str
    signals: list[FeedbackSignalIn]


class ApproveRequest(BaseModel):
    reviewer_id: str
    eval_score: float | None = Field(default=None, ge=0.0, le=1.0)


class RejectRequest(BaseModel):
    reviewer_id: str
    signals: list[FeedbackSignalIn]


class RepairQueueItem(BaseModel):
    id: str
    generation_id: str
    skill_type: str
    deck_id: str
    retry_count: int
    last_error: str | None
    status: str
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_generation_or_404(generation_id: str, db: AsyncSession) -> Generation:
    gen = await db.get(Generation, uuid.UUID(generation_id))
    if gen is None:
        raise HTTPException(status_code=404, detail=f"Generation {generation_id} not found")
    return gen


async def _embed_and_save(generation_id: str, output_text: str, db: AsyncSession) -> None:
    """Generate embedding for approved output and write it back to the generation row."""
    try:
        from ppt_agent.memory.retrieval import embed_text
        vec = await embed_text(output_text)
        await save_embedding(generation_id, vec, db)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Embedding failed for generation %s: %s", generation_id, exc
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{generation_id}/feedback")
async def post_feedback(
    generation_id: str,
    body: FeedbackRequest,
    db: DB,
):
    """Record feedback signals without changing generation status."""
    gen = await _get_generation_or_404(generation_id, db)

    signals = [
        FeedbackSignal(
            signal_type=s.signal_type,
            severity=s.severity,
            section_id=s.section_id,
            reviewer_note=s.reviewer_note,
        )
        for s in body.signals
    ]
    await record_feedback(generation_id, signals, body.reviewer_id, db)

    # Upsert pattern candidates from high-severity signals
    for sig in signals:
        if sig.severity >= 2 and sig.reviewer_note:
            await upsert_candidate(
                skill_type=gen.skill_type,
                pattern_text=sig.reviewer_note,
                source_feedback_ids=[],
                db=db,
            )

    return {"status": "ok", "signals_recorded": len(signals)}


@router.post("/{generation_id}/approve")
async def approve_generation(
    generation_id: str,
    body: ApproveRequest,
    background_tasks: BackgroundTasks,
    db: DB,
):
    """
    Approve a generation:
    - status → approved
    - eval_score written if provided
    - embedding computed and stored in the background
    """
    gen = await _get_generation_or_404(generation_id, db)

    if gen.status == "approved":
        return {"status": "already_approved"}

    gen.status = "approved"
    if body.eval_score is not None:
        gen.eval_score = body.eval_score

    if gen.output_text:
        # Embed + auto-score with G-Eval in background
        background_tasks.add_task(_embed_and_save, generation_id, gen.output_text, db)
        if body.eval_score is None:
            background_tasks.add_task(_geval_score_bg, generation_id, gen.output_text, gen.skill_type)

    return {"status": "approved", "generation_id": generation_id}


@router.post("/{generation_id}/reject")
async def reject_generation(
    generation_id: str,
    body: RejectRequest,
    background_tasks: BackgroundTasks,
    db: DB,
):
    """
    Reject a generation:
    - status → rejected
    - feedback signals recorded
    - test case generated in background
    """
    gen = await _get_generation_or_404(generation_id, db)

    gen.status = "rejected"

    signals = [
        FeedbackSignal(
            signal_type=s.signal_type,
            severity=s.severity,
            section_id=s.section_id,
            reviewer_note=s.reviewer_note,
        )
        for s in body.signals
    ]
    if signals:
        await record_feedback(generation_id, signals, body.reviewer_id, db)

    # Auto-generate regression test case + maybe trigger optimizer
    background_tasks.add_task(_generate_test_case_bg, generation_id)
    background_tasks.add_task(_maybe_optimize_bg, gen.skill_type)

    return {"status": "rejected", "generation_id": generation_id}


async def _generate_test_case_bg(generation_id: str) -> None:
    try:
        from ppt_agent.evals.test_case_generator import generate_test_case
        await generate_test_case(generation_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Test case generation failed for %s: %s", generation_id, exc
        )


async def _geval_score_bg(generation_id: str, output_text: str, skill_type: str) -> None:
    """Run G-Eval scoring and write the result back to the generation row."""
    try:
        import asyncio
        from ppt_agent.optimizer.geval import score_reading_material
        from ppt_agent.db.session import get_db_session
        from ppt_agent.db.models import Generation
        import uuid

        score, reasoning = await asyncio.to_thread(score_reading_material, output_text, skill_type)

        async with get_db_session() as db:
            gen = await db.get(Generation, uuid.UUID(generation_id))
            if gen and gen.eval_score is None:
                gen.eval_score = round(score, 2)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "G-Eval scoring failed for %s: %s", generation_id, exc
        )


async def _maybe_optimize_bg(skill_type: str) -> None:
    """Trigger GEPA optimizer after a rejection — runs only if enough examples exist."""
    try:
        from ppt_agent.optimizer.prompt_optimizer import maybe_optimize
        await maybe_optimize(skill_type)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "GEPA optimizer failed for %s: %s", skill_type, exc
        )


@router.get("/repair-queue", response_model=list[RepairQueueItem])
async def get_repair_queue(
    db: DB,
    skip: int = 0,
    limit: int = 50,
    status: str = "pending",
):
    """Return repair-queue items joined with generation metadata, sorted by age."""
    rows = (
        await db.execute(
            select(RepairQueue, Generation)
            .join(Generation, Generation.id == RepairQueue.generation_id)
            .where(RepairQueue.status == status)
            .order_by(RepairQueue.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
    ).all()

    return [
        RepairQueueItem(
            id=str(rq.id),
            generation_id=str(gen.id),
            skill_type=gen.skill_type,
            deck_id=str(gen.deck_id),
            retry_count=rq.retry_count,
            last_error=rq.last_error,
            status=rq.status,
            created_at=rq.created_at.isoformat(),
        )
        for rq, gen in rows
    ]

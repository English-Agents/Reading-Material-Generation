"""
Source content API — manage developer-curated reference passages per deck.

Routes:
  POST   /source-content/{deck_id}          — add a passage (max 2,000 chars)
  GET    /source-content/{deck_id}          — list all passages + budget usage
  DELETE /source-content/{deck_id}/{id}     — remove a passage
  POST   /source-content/{deck_id}/validate — run alignment validator on all passages
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ppt_agent.api.deps import get_db
from ppt_agent.config.settings import settings as _settings
from ppt_agent.db.models import SourceContent

MAX_SOURCE_CHARS_PER_DECK = _settings.max_source_chars_per_deck

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


# ── Schemas ───────────────────────────────────────────────────────────────────

class SourceContentIn(BaseModel):
    topic_label: str
    passage_text: str = Field(..., min_length=50, max_length=2000)
    source_title: Optional[str] = None
    page_ref: Optional[str] = None
    author: Optional[str] = None
    uploaded_by: Optional[str] = None


class SourceContentOut(BaseModel):
    id: str
    deck_id: str
    topic_label: str
    passage_text: str
    source_title: Optional[str]
    page_ref: Optional[str]
    author: Optional[str]
    alignment_score: Optional[float]
    alignment_verdict: Optional[str]
    alignment_reason: Optional[str]
    char_count: int
    created_at: str


class SourceContentListResponse(BaseModel):
    passages: list[SourceContentOut]
    total_chars: int
    budget_chars: int
    budget_remaining: int


class ValidationRequest(BaseModel):
    topic_text: str
    override_warn: bool = False     # developer explicitly confirms warn-level passages


class PassageValidationResult(BaseModel):
    passage_id: str
    source_title: str
    alignment_score: float
    verdict: str
    reason: str


class ValidationResponse(BaseModel):
    topic_id: str
    topic_text: str
    overall_verdict: str
    overall_score: float
    threshold: float
    passage_results: list[PassageValidationResult]
    generation_blocked: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_out(p: SourceContent) -> SourceContentOut:
    return SourceContentOut(
        id=str(p.id),
        deck_id=str(p.deck_id),
        topic_label=p.topic_label,
        passage_text=p.passage_text,
        source_title=p.source_title,
        page_ref=p.page_ref,
        author=p.author,
        alignment_score=float(p.alignment_score) if p.alignment_score is not None else None,
        alignment_verdict=p.alignment_verdict,
        alignment_reason=p.alignment_reason,
        char_count=len(p.passage_text),
        created_at=p.created_at.isoformat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{deck_id}", response_model=SourceContentOut, status_code=201)
async def add_passage(deck_id: str, body: SourceContentIn, db: DB):
    """
    Add a reference passage to a deck. Max 2,000 chars per passage.
    Alignment is scored immediately via claude-haiku; result written to the row.
    """
    # Check budget before adding
    existing = (
        await db.execute(select(SourceContent).where(SourceContent.deck_id == uuid.UUID(deck_id)))
    ).scalars().all()

    current_total = sum(len(p.passage_text) for p in existing)
    if current_total + len(body.passage_text) > MAX_SOURCE_CHARS_PER_DECK:
        remaining = MAX_SOURCE_CHARS_PER_DECK - current_total
        raise HTTPException(
            status_code=422,
            detail=(
                f"Adding this passage ({len(body.passage_text):,} chars) would exceed the "
                f"{MAX_SOURCE_CHARS_PER_DECK:,}-char deck budget. "
                f"You have {remaining:,} chars remaining."
            ),
        )

    row = SourceContent(
        deck_id=uuid.UUID(deck_id),
        topic_label=body.topic_label,
        passage_text=body.passage_text,
        source_title=body.source_title,
        page_ref=body.page_ref,
        author=body.author,
        uploaded_by=body.uploaded_by,
    )
    db.add(row)
    await db.flush()   # get the row id before alignment call

    # Run alignment immediately so the caller sees scores in the response
    try:
        from ppt_agent.skills.alignment_validator import validate_passages as _validate
        result = await _validate(
            topic_id=deck_id,
            topic_text=body.topic_label,
            passages=[{
                "id": str(row.id),
                "passage_text": row.passage_text,
                "source_title": row.source_title,
                "page_ref": row.page_ref,
            }],
        )
        if result.passage_results:
            pr = result.passage_results[0]
            row.alignment_score = pr.alignment_score
            row.alignment_verdict = pr.verdict
            row.alignment_reason = pr.reason
    except Exception as exc:
        # Alignment failure must not block the passage from being saved
        import logging
        logging.getLogger(__name__).warning("Alignment check failed on POST: %s", exc)

    return _to_out(row)


@router.get("/{deck_id}", response_model=SourceContentListResponse)
async def list_passages(deck_id: str, db: DB):
    """List all source passages for a deck with budget usage."""
    rows = (
        await db.execute(
            select(SourceContent)
            .where(SourceContent.deck_id == uuid.UUID(deck_id))
            .order_by(SourceContent.created_at.asc())
        )
    ).scalars().all()

    total_chars = sum(len(p.passage_text) for p in rows)
    return SourceContentListResponse(
        passages=[_to_out(p) for p in rows],
        total_chars=total_chars,
        budget_chars=MAX_SOURCE_CHARS_PER_DECK,
        budget_remaining=max(0, MAX_SOURCE_CHARS_PER_DECK - total_chars),
    )


@router.delete("/{deck_id}/{passage_id}", status_code=204)
async def delete_passage(deck_id: str, passage_id: str, db: DB):
    """Remove a source passage."""
    row = await db.get(SourceContent, uuid.UUID(passage_id))
    if row is None or str(row.deck_id) != deck_id:
        raise HTTPException(status_code=404, detail="Passage not found")
    await db.delete(row)


@router.post("/{deck_id}/validate", response_model=ValidationResponse)
async def validate_passages(deck_id: str, body: ValidationRequest, db: DB):
    """
    Run alignment validator on all passages for the deck.
    Uses claude-haiku-4-5 — one call per passage.
    Writes alignment_score and alignment_verdict back to each passage row.
    """
    rows = (
        await db.execute(
            select(SourceContent)
            .where(SourceContent.deck_id == uuid.UUID(deck_id))
            .order_by(SourceContent.created_at.asc())
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(status_code=422, detail="No source passages found for this deck.")

    from ppt_agent.skills.alignment_validator import validate_passages as _validate
    result = await _validate(
        topic_id=deck_id,
        topic_text=body.topic_text,
        passages=[
            {
                "id": str(r.id),
                "passage_text": r.passage_text,
                "source_title": r.source_title,
                "page_ref": r.page_ref,
            }
            for r in rows
        ],
    )

    # Write scores back to DB
    id_map = {str(r.id): r for r in rows}
    for pr in result.passage_results:
        row = id_map.get(pr.passage_id)
        if row:
            row.alignment_score = pr.alignment_score
            row.alignment_verdict = pr.verdict
            row.alignment_reason = pr.reason

    # Determine if generation is blocked
    has_fail = any(pr.verdict == "fail" for pr in result.passage_results)
    has_warn = any(pr.verdict == "warn" for pr in result.passage_results)
    generation_blocked = has_fail or (has_warn and not body.override_warn)

    if has_fail:
        message = (
            f"{sum(1 for r in result.passage_results if r.verdict == 'fail')} passage(s) failed "
            "alignment check. Remove them before generating."
        )
    elif has_warn and not body.override_warn:
        message = (
            f"{sum(1 for r in result.passage_results if r.verdict == 'warn')} passage(s) are "
            "marginally relevant. Set override_warn=true to proceed anyway, or remove them."
        )
    else:
        message = "All passages passed alignment check. Generation is unblocked."

    return ValidationResponse(
        topic_id=deck_id,
        topic_text=body.topic_text,
        overall_verdict=result.verdict,
        overall_score=result.alignment_score,
        threshold=result.threshold,
        passage_results=[
            PassageValidationResult(
                passage_id=pr.passage_id,
                source_title=pr.source_title,
                alignment_score=pr.alignment_score,
                verdict=pr.verdict,
                reason=pr.reason,
            )
            for pr in result.passage_results
        ],
        generation_blocked=generation_blocked,
        message=message,
    )

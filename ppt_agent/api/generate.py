"""
POST /generate — one LLM call per deck, no per-slide generation.

Flow:
  1. Parse PPTX → extract all slide text
  2. Single LLM call via deck_compiler → one reading material document
  3. Store as deck_reading Generation, return deck_generation_id
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ppt_agent.api.deps import get_db

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide, parse as parse_pptx

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateByUrlRequest(BaseModel):
    url: str
    reviewer_id: Optional[str] = None


class GenerateResponse(BaseModel):
    deck_id: str
    slide_count: int
    deck_generation_id: str


# ── Core helper ───────────────────────────────────────────────────────────────

async def _process_pptx_bytes(pptx_bytes: bytes, source_url: str) -> GenerateResponse:
    deck_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(pptx_bytes)
        tmp_path = tmp.name

    slides: list[ParsedSlide] = parse_pptx(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)

    if not slides:
        raise HTTPException(status_code=422, detail="No slides could be extracted from the file.")

    # ONE LLM call for the whole deck
    from ppt_agent.skills.deck_compiler import compile_deck
    try:
        deck_gen_id = await compile_deck(deck_id, slides)
    except Exception as exc:
        logger.error("Deck compilation failed for deck %s: %s", deck_id, exc)
        raise HTTPException(status_code=500, detail=f"Reading material generation failed: {exc}")

    return GenerateResponse(
        deck_id=deck_id,
        slide_count=len(slides),
        deck_generation_id=deck_gen_id,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/file", response_model=GenerateResponse)
async def generate_from_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=422, detail="Only .pptx files are supported.")

    pptx_bytes = await file.read()
    if len(pptx_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    return await _process_pptx_bytes(pptx_bytes, source_url=file.filename)


@router.post("/url", response_model=GenerateResponse)
async def generate_from_url(body: GenerateByUrlRequest):
    import re
    import httpx

    url = body.url.strip()
    m = re.search(r"docs\.google\.com/presentation/d/([A-Za-z0-9_-]+)", url)

    if m:
        try:
            from ppt_agent.integrations.google_slides import export_as_pptx
            pptx_bytes = await export_as_pptx(m.group(1))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Google Slides export failed: {exc}")
    elif url.lower().endswith(".pptx"):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                pptx_bytes = resp.content
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download PPTX: {exc}")
    else:
        raise HTTPException(
            status_code=422,
            detail="URL must be a Google Slides link or a direct .pptx URL.",
        )

    return await _process_pptx_bytes(pptx_bytes, source_url=url)


@router.get("/generations")
async def list_generations(
    db: AsyncSession = Depends(get_db),
    deck_id: Optional[str] = None,
    status: Optional[str] = None,
    skill_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    from sqlalchemy import select
    from ppt_agent.db.models import Generation

    q = select(Generation).where(Generation.is_shadow == False)
    if deck_id:
        q = q.where(Generation.deck_id == uuid.UUID(deck_id))
    if status:
        q = q.where(Generation.status == status)
    if skill_type:
        q = q.where(Generation.skill_type == skill_type)

    q = q.order_by(Generation.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    return [
        {
            "generation_id": str(g.id),
            "deck_id": str(g.deck_id),
            "slide_index": g.slide_index,
            "skill_type": g.skill_type,
            "status": g.status,
            "eval_score": float(g.eval_score) if g.eval_score is not None else None,
            "token_cost_usd": float(g.token_cost_usd) if g.token_cost_usd is not None else None,
            "output_text": g.output_text,
            "topic_outline": json.loads(g.topic_outline) if g.topic_outline else None,
            "topic_coverage_score": float(g.topic_coverage_score) if g.topic_coverage_score is not None else None,
            "topic_coverage_verdict": g.topic_coverage_verdict,
            "topic_coverage_reason": g.topic_coverage_reason,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in rows
    ]

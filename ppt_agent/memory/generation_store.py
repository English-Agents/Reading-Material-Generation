"""
generation_store.py — read/write access to the generations table.

Key operations:
  - get_similar_generations: pgvector cosine similarity search
  - save_embedding: write embedding back after approval
  - get_cost_quality_scatter: analytics helper for ops dashboard
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from ppt_agent.db.models import Generation
from ppt_agent.memory.types import SimilarOutput

if TYPE_CHECKING:
    import numpy as np
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_similar_generations(
    embedding: "np.ndarray",
    skill_type: str,
    db: "AsyncSession",
    k: int = 5,
) -> list[SimilarOutput]:
    """
    Return the k most similar approved generations using pgvector cosine distance.
    Passes the numpy array as a plain Python list — asyncpg handles the cast.
    """
    vec = embedding.tolist()

    rows = (
        await db.execute(
            select(
                Generation.id,
                Generation.output_text,
                Generation.skill_type,
                Generation.eval_score,
                # cosine similarity = 1 - cosine distance
                (1 - Generation.embedding.op("<=>")(vec)).label("similarity"),
            )
            .where(
                Generation.skill_type == skill_type,
                Generation.status == "approved",
                Generation.embedding.is_not(None),
            )
            .order_by(Generation.embedding.op("<=>")(vec))
            .limit(k)
        )
    ).all()

    return [
        SimilarOutput(
            generation_id=str(row.id),
            output_text=row.output_text or "",
            skill_type=row.skill_type,
            eval_score=float(row.eval_score) if row.eval_score is not None else None,
            similarity=float(row.similarity),
        )
        for row in rows
    ]


async def save_embedding(
    generation_id: str,
    embedding: "np.ndarray",
    db: "AsyncSession",
) -> None:
    """Write embedding vector back to the generation row (called on approval)."""
    import uuid

    gen = await db.get(Generation, uuid.UUID(generation_id))
    if gen is None:
        logger.warning("save_embedding: generation %s not found", generation_id)
        return
    gen.embedding = embedding.tolist()


async def get_cost_quality_scatter(
    skill_type: str,
    db: "AsyncSession",
    limit: int = 200,
) -> list[tuple[float, float]]:
    """
    Returns list of (token_cost_usd, eval_score) for the last `limit` approved
    generations of a skill. Used by the ops dashboard cost/quality chart.
    """
    rows = (
        await db.execute(
            select(Generation.token_cost_usd, Generation.eval_score)
            .where(
                Generation.skill_type == skill_type,
                Generation.status == "approved",
                Generation.token_cost_usd.is_not(None),
                Generation.eval_score.is_not(None),
            )
            .order_by(Generation.created_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        (float(row.token_cost_usd), float(row.eval_score))
        for row in rows
    ]


async def get_recent_eval_scores(
    skill_type: str,
    db: "AsyncSession",
    window: int = 100,
) -> list[float]:
    """Return the last `window` eval scores for a skill (for score-drop alert)."""
    rows = (
        await db.execute(
            select(Generation.eval_score)
            .where(
                Generation.skill_type == skill_type,
                Generation.status == "approved",
                Generation.eval_score.is_not(None),
                Generation.is_shadow == False,
            )
            .order_by(Generation.created_at.desc())
            .limit(window)
        )
    ).scalars().all()

    return [float(s) for s in rows]

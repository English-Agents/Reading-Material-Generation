"""
pattern_store.py — manage the pattern_memory table.

Patterns are learned rules extracted from repeated reviewer feedback.
Lifecycle: candidate → active (when example_count hits threshold) → retired.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select, text, update

from ppt_agent.db.models import PatternMemory
from ppt_agent.memory.types import PatternRule

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_active_patterns(
    skill_type: str,
    db: "AsyncSession",
) -> list[PatternRule]:
    """Return all active patterns for a skill, ordered by confidence desc."""
    rows = (
        await db.execute(
            select(PatternMemory)
            .where(
                PatternMemory.skill_type == skill_type,
                PatternMemory.status == "active",
            )
            .order_by(PatternMemory.confidence.desc())
        )
    ).scalars().all()

    return [
        PatternRule(
            pattern_id=str(row.id),
            skill_type=row.skill_type,
            pattern_text=row.pattern_text,
            confidence=float(row.confidence),
        )
        for row in rows
    ]


async def upsert_candidate(
    skill_type: str,
    pattern_text: str,
    source_feedback_ids: list[str],
    db: "AsyncSession",
) -> PatternMemory:
    """
    Insert a new candidate pattern, or increment example_count if an
    identical pattern_text already exists for this skill.
    Promotes to 'active' if example_count reaches the threshold.
    """
    from ppt_agent.config.settings import settings

    existing = (
        await db.execute(
            select(PatternMemory).where(
                PatternMemory.skill_type == skill_type,
                PatternMemory.pattern_text == pattern_text,
                PatternMemory.status.in_(["candidate", "active"]),
            )
        )
    ).scalar_one_or_none()

    if existing:
        pattern = existing
    else:
        pattern = PatternMemory(
            skill_type=skill_type,
            pattern_text=pattern_text,
            confidence=0.0,
            example_count=0,
            status="candidate",
            source_feedback_ids=[],
        )
        db.add(pattern)
        await db.flush()

    await _increment_example_count(pattern.id, source_feedback_ids, db)

    # Re-fetch to get updated count
    await db.refresh(pattern)
    _maybe_promote(pattern, settings.pattern_promotion_threshold)

    return pattern


async def _increment_example_count(
    pattern_id: uuid.UUID,
    new_feedback_ids: list[str],
    db: "AsyncSession",
) -> None:
    """Atomic increment using UPDATE ... RETURNING."""
    result = await db.execute(
        text(
            "UPDATE pattern_memory "
            "SET example_count = example_count + 1, "
            "    source_feedback_ids = source_feedback_ids || :new_ids::jsonb "
            "WHERE id = :id "
            "RETURNING example_count, confidence"
        ),
        {
            "id": str(pattern_id),
            "new_ids": f'[{", ".join(repr(fid) for fid in new_feedback_ids)}]',
        },
    )
    row = result.fetchone()
    if row:
        logger.debug("Pattern %s: example_count=%d", pattern_id, row.example_count)


def _maybe_promote(pattern: PatternMemory, threshold: int) -> None:
    if pattern.status == "candidate" and pattern.example_count >= threshold:
        pattern.status = "active"
        pattern.confidence = min(1.0, pattern.example_count / (threshold * 2))
        logger.info(
            "Promoted pattern %s for %s (count=%d)",
            pattern.id, pattern.skill_type, pattern.example_count,
        )


async def retire_pattern(pattern_id: str, db: "AsyncSession") -> None:
    pattern = await db.get(PatternMemory, uuid.UUID(pattern_id))
    if pattern:
        pattern.status = "retired"
        logger.info("Retired pattern %s", pattern_id)


async def get_all_candidate_patterns(
    skill_type: str,
    db: "AsyncSession",
) -> list[PatternMemory]:
    rows = (
        await db.execute(
            select(PatternMemory).where(
                PatternMemory.skill_type == skill_type,
                PatternMemory.status == "candidate",
            )
        )
    ).scalars().all()
    return list(rows)

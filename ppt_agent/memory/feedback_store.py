"""
feedback_store.py — write feedback signals and aggregate reviewer preferences.

SignalType values (9 total, must match the DB CHECK constraint):
  too_long | too_short | wrong_tone | missing_example | factual_error |
  format_violation | unnecessary_diagram | needs_diagram | unclear_explanation
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ppt_agent.db.models import Feedback
from ppt_agent.memory.types import ReviewerPref

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    WRONG_TONE = "wrong_tone"
    MISSING_EXAMPLE = "missing_example"
    FACTUAL_ERROR = "factual_error"
    FORMAT_VIOLATION = "format_violation"
    UNNECESSARY_DIAGRAM = "unnecessary_diagram"
    NEEDS_DIAGRAM = "needs_diagram"
    UNCLEAR_EXPLANATION = "unclear_explanation"


@dataclass
class FeedbackSignal:
    signal_type: str        # one of SignalType values
    severity: int           # 1-3
    section_id: str = ""
    reviewer_note: str = ""


async def record_feedback(
    generation_id: str,
    signals: list[FeedbackSignal],
    reviewer_id: str,
    db: "AsyncSession",
) -> list[Feedback]:
    """Insert one Feedback row per signal. Returns created rows."""
    rows: list[Feedback] = []
    for sig in signals:
        row = Feedback(
            generation_id=uuid.UUID(generation_id),
            section_id=sig.section_id or None,
            reviewer_id=reviewer_id,
            signal_type=sig.signal_type,
            severity=sig.severity,
            reviewer_note=sig.reviewer_note or None,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    logger.debug(
        "Recorded %d feedback signals for generation %s",
        len(signals), generation_id,
    )
    return rows


async def get_reviewer_prefs(
    skill_type: str,
    db: "AsyncSession",
    top_n: int = 5,
) -> list[ReviewerPref]:
    """
    Aggregate feedback signals for a skill across all reviewers.
    Returns the top-N most frequent signals with avg severity.
    """
    from ppt_agent.db.models import Generation

    rows = (
        await db.execute(
            select(
                Feedback.signal_type,
                func.count(Feedback.id).label("frequency"),
                func.avg(Feedback.severity).label("avg_severity"),
            )
            .join(Generation, Generation.id == Feedback.generation_id)
            .where(Generation.skill_type == skill_type)
            .group_by(Feedback.signal_type)
            .order_by(func.count(Feedback.id).desc())
            .limit(top_n)
        )
    ).all()

    return [
        ReviewerPref(
            signal_type=row.signal_type,
            frequency=int(row.frequency),
            avg_severity=float(row.avg_severity),
        )
        for row in rows
    ]


async def get_feedback_for_generation(
    generation_id: str,
    db: "AsyncSession",
) -> list[Feedback]:
    rows = (
        await db.execute(
            select(Feedback).where(
                Feedback.generation_id == uuid.UUID(generation_id)
            )
        )
    ).scalars().all()
    return list(rows)

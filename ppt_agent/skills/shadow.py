from __future__ import annotations

import hashlib
import logging
import sys
import uuid
from pathlib import Path

from ppt_agent.config.settings import settings
from ppt_agent.memory.types import EMPTY_CONTEXT
from ppt_agent.skills.circuit_breaker import RepairRequired

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide

logger = logging.getLogger(__name__)


def _shadow_traffic_pct(skill_type: str) -> float:
    cfg = settings.shadow_config.get(skill_type, {})
    return float(cfg.get("traffic_pct", 0.0))


def _deck_in_shadow(deck_id: str, traffic_pct: float) -> bool:
    """Deterministic per-deck decision: all slides in one deck go the same way."""
    if traffic_pct <= 0.0:
        return False
    digest = int(hashlib.md5(deck_id.encode()).hexdigest(), 16)
    # Map 128-bit int to [0, 1)
    ratio = digest / (2**128)
    return ratio < traffic_pct


async def maybe_run_shadow(
    slide: ParsedSlide,
    skill_type: str,
    deck_id: str,
    *,
    db,
) -> None:
    traffic_pct = _shadow_traffic_pct(skill_type)
    if not _deck_in_shadow(deck_id, traffic_pct):
        return

    from ppt_agent.db.models import Generation
    from ppt_agent.memory.prompt_store import get_shadow

    shadow_version = await get_shadow(skill_type, db)
    if shadow_version is None:
        logger.debug("No shadow prompt version for skill_type=%s", skill_type)
        return

    from ppt_agent.skills.router import _get_skill_fn

    gen = Generation(
        deck_id=uuid.UUID(deck_id),
        skill_type=skill_type,
        slide_index=slide.slide_index,
        prompt_version_id=shadow_version.id,
        status="pending",
        is_shadow=True,
    )
    db.add(gen)
    await db.flush()
    generation_id = str(gen.id)

    skill_fn = _get_skill_fn(skill_type)
    result = await skill_fn(
        slide,
        shadow_version.prompt_text,
        {},
        EMPTY_CONTEXT,
        generation_id=generation_id,
        db=db,
    )

    if not isinstance(result, RepairRequired):
        gen.output_text = result

    logger.debug("Shadow generation %s completed for deck=%s", generation_id, deck_id)


async def evaluate_shadow_promotions(db) -> None:
    """
    Called by the ops background job every 15 minutes.
    Compares shadow avg_rubric_score vs active avg_rubric_score.
    Promotes if margin >= SHADOW_PROMOTION_MARGIN, otherwise retires.
    """
    from sqlalchemy import func, select, text

    from ppt_agent.db.models import Generation, PromptVersion
    from ppt_agent.memory.prompt_store import get_active, promote, retire

    shadow_versions = (
        await db.execute(
            select(PromptVersion).where(PromptVersion.status == "shadow")
        )
    ).scalars().all()

    for shadow in shadow_versions:
        skill_type = shadow.skill_type

        shadow_avg = (
            await db.execute(
                select(func.avg(Generation.eval_score))
                .where(
                    Generation.prompt_version_id == shadow.id,
                    Generation.eval_score.is_not(None),
                )
            )
        ).scalar()

        active = await get_active(skill_type, db)
        if active is None or shadow_avg is None:
            continue

        active_avg = (
            await db.execute(
                select(func.avg(Generation.eval_score))
                .where(
                    Generation.prompt_version_id == active.id,
                    Generation.eval_score.is_not(None),
                )
            )
        ).scalar()

        if active_avg is None:
            continue

        margin = float(shadow_avg) - float(active_avg)
        if margin >= settings.shadow_promotion_margin:
            logger.info(
                "Promoting shadow %s for %s (margin=%.3f)",
                shadow.id, skill_type, margin,
            )
            await promote(shadow.id, db)
        else:
            logger.info(
                "Retiring shadow %s for %s (margin=%.3f < threshold)",
                shadow.id, skill_type, margin,
            )
            await retire(shadow.id, db)

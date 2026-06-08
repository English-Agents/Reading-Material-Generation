from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Callable

from ppt_agent.memory.types import EMPTY_CONTEXT, MemoryContext
from ppt_agent.skills.circuit_breaker import RepairRequired

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_classifier import SlideType
from slide_parser import ParsedSlide

logger = logging.getLogger(__name__)

# Lazy import at call time to avoid circular-import at module level
# Each value is imported inside _get_skill_fn()


def _get_skill_fn(skill_type: str) -> Callable:
    if skill_type == "concept_explainer":
        from ppt_agent.skills import concept_explainer
        return concept_explainer.run
    if skill_type == "code_walkthrough":
        from ppt_agent.skills import code_walkthrough
        return code_walkthrough.run
    if skill_type == "diagram_describer":
        from ppt_agent.skills import diagram_describer
        return diagram_describer.run
    if skill_type == "figure_caption":
        from ppt_agent.skills import figure_caption
        return figure_caption.run
    if skill_type == "quiz_generator":
        from ppt_agent.skills import quiz_generator
        return quiz_generator.run
    raise ValueError(f"Unknown skill_type: {skill_type}")


_SLIDE_TYPE_TO_SKILL: dict[SlideType, str] = {
    SlideType.TITLE: "concept_explainer",
    SlideType.CONCEPT: "concept_explainer",
    SlideType.CODE: "code_walkthrough",
    SlideType.DIAGRAM: "diagram_describer",
    SlideType.IMAGE_HEAVY: "figure_caption",
}


def _resolve_skill(slide: ParsedSlide, slide_type: SlideType, is_technical_diagram: bool | None) -> str:
    """
    Determine final skill_type.
    If a single image was pre-cached as non-technical (is_technical_diagram=False),
    override diagram_describer → figure_caption regardless of classifier result.
    """
    base = _SLIDE_TYPE_TO_SKILL.get(slide_type, "concept_explainer")
    if base == "diagram_describer" and is_technical_diagram is False:
        return "figure_caption"
    return base


async def dispatch(
    slide: ParsedSlide,
    slide_type: SlideType,
    deck_id: str,
    *,
    db,
    is_technical_diagram: bool | None = None,
    memory_context: MemoryContext | None = None,
    run_shadow: bool = True,
) -> str | RepairRequired:
    """
    Main entry point. Creates a generation row, calls the appropriate skill,
    optionally fires shadow generation as a background task.
    """
    from ppt_agent.db.models import Generation
    from ppt_agent.memory.prompt_store import get_active

    skill_type = _resolve_skill(slide, slide_type, is_technical_diagram)
    ctx = memory_context or EMPTY_CONTEXT

    prompt_version = await get_active(skill_type, db)
    if prompt_version is None:
        logger.error("No active prompt version for skill_type=%s", skill_type)
        raise RuntimeError(f"No active prompt for {skill_type}")

    # Create pending generation row
    gen = Generation(
        deck_id=uuid.UUID(deck_id),
        skill_type=skill_type,
        slide_index=slide.slide_index,
        prompt_version_id=prompt_version.id,
        status="pending",
        is_shadow=False,
    )
    db.add(gen)
    await db.flush()
    generation_id = str(gen.id)

    skill_fn = _get_skill_fn(skill_type)
    result = await skill_fn(
        slide,
        prompt_version.prompt_text,
        {},
        ctx,
        generation_id=generation_id,
        db=db,
    )

    if isinstance(result, RepairRequired):
        return result

    gen.output_text = result
    gen.status = "pending"  # awaiting review

    if run_shadow:
        asyncio.create_task(
            _run_shadow_task(slide, skill_type, deck_id)
        )

    return result


async def _run_shadow_task(
    slide: ParsedSlide,
    skill_type: str,
    deck_id: str,
) -> None:
    # Shadow runs in its own session — the request session may already be
    # committed or closed by the time this background task executes.
    try:
        from ppt_agent.db.session import get_db_session
        from ppt_agent.skills.shadow import maybe_run_shadow
        async with get_db_session() as db:
            await maybe_run_shadow(slide, skill_type, deck_id, db=db)
    except Exception as exc:
        logger.warning("Shadow task failed for deck=%s skill=%s: %s", deck_id, skill_type, exc)

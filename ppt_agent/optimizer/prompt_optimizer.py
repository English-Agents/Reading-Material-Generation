"""
GEPA-based prompt optimizer for reading material generation.

Triggered by the ops background job when enough approved/rejected
generations have accumulated (MIN_EXAMPLES = 10 per skill type).

Flow:
  1. Load approved (positive) + rejected (negative) deck_reading generations
  2. Build DSPy training examples
  3. Run GEPA optimizer to improve the deck_reading prompt
  4. Store the optimized prompt as a new 'candidate' PromptVersion
"""
from __future__ import annotations

import logging
import os

import dspy
from dspy.teleprompt import GEPA
from dspy.teleprompt.gepa.gepa import GEPAFeedbackMetric

from ppt_agent.config.settings import settings

logger = logging.getLogger(__name__)

MIN_EXAMPLES = 10   # minimum approved+rejected before optimization runs


# ── DSPy program being optimized ──────────────────────────────────────────

class _GenerateReadingMaterial(dspy.Signature):
    """Generate a comprehensive reading material document for English verbal ability placement test prep."""
    slide_content: str = dspy.InputField(desc="Combined slide titles and body text")
    reading_material: str = dspy.OutputField(desc="Complete reading material in markdown format")


class ReadingMaterialProgram(dspy.Module):
    def __init__(self) -> None:
        self.generate = dspy.ChainOfThought(_GenerateReadingMaterial)

    def forward(self, slide_content: str) -> dspy.Prediction:
        return self.generate(slide_content=slide_content)


# ── GEPA metric ───────────────────────────────────────────────────────────

def _build_gepa_metric() -> GEPAFeedbackMetric:
    """
    GEPA metric: approved generations score 1.0, rejected score 0.0.
    Also uses G-Eval for intermediate scoring when human label is absent.
    """
    from ppt_agent.optimizer.geval import score_reading_material

    def metric(example: dspy.Example, pred: dspy.Prediction, trace=None) -> float:
        label = getattr(example, "label", None)
        if label == "approved":
            return 1.0
        if label == "rejected":
            return 0.0
        # No human label — use G-Eval
        output = getattr(pred, "reading_material", "") or ""
        score, _ = score_reading_material(output, "deck_reading")
        return score

    return GEPAFeedbackMetric(metric)


# ── Main entry point ──────────────────────────────────────────────────────

async def maybe_optimize(skill_type: str = "deck_reading") -> bool:
    """
    Run GEPA optimization if enough labelled examples exist.
    Returns True if optimization ran, False if skipped.
    Stores the optimized prompt as a new PromptVersion with status='candidate'.
    """
    from sqlalchemy import select

    from ppt_agent.db.models import Generation, PromptVersion
    from ppt_agent.db.session import get_db_session
    from ppt_agent.memory.prompt_store import get_active

    async with get_db_session() as db:
        approved = (
            await db.execute(
                select(Generation)
                .where(
                    Generation.skill_type == skill_type,
                    Generation.status == "approved",
                    Generation.is_shadow == False,
                    Generation.output_text.is_not(None),
                )
                .limit(50)
            )
        ).scalars().all()

        rejected = (
            await db.execute(
                select(Generation)
                .where(
                    Generation.skill_type == skill_type,
                    Generation.status == "rejected",
                    Generation.is_shadow == False,
                    Generation.output_text.is_not(None),
                )
                .limit(50)
            )
        ).scalars().all()

        if len(approved) + len(rejected) < MIN_EXAMPLES:
            logger.info(
                "Skipping GEPA optimize for %s — only %d labelled examples (need %d)",
                skill_type, len(approved) + len(rejected), MIN_EXAMPLES,
            )
            return False

        active_prompt = await get_active(skill_type, db)
        if active_prompt is None:
            logger.warning("No active prompt for %s, skipping optimization", skill_type)
            return False

        active_prompt_text = active_prompt.prompt_text
        active_prompt_id = active_prompt.id

    # Build DSPy training set
    trainset: list[dspy.Example] = []
    for gen in approved:
        trainset.append(
            dspy.Example(
                slide_content=f"deck_id={gen.deck_id}",
                reading_material=gen.output_text,
                label="approved",
            ).with_inputs("slide_content")
        )
    for gen in rejected:
        trainset.append(
            dspy.Example(
                slide_content=f"deck_id={gen.deck_id}",
                reading_material=gen.output_text or "",
                label="rejected",
            ).with_inputs("slide_content")
        )

    # Configure DSPy LM
    lm = dspy.LM(
        model=f"openai/{settings.generation_model}",
        api_key=settings.anthropic_api_key,
        api_base=settings.llm_base_url,
        cache=False,
    )
    dspy.configure(lm=lm)

    # Run GEPA
    program = ReadingMaterialProgram()
    gepa = GEPA(metric=_build_gepa_metric(), auto="light", seed=42)

    try:
        optimized = gepa.compile(program, trainset=trainset)
    except Exception as exc:
        logger.error("GEPA optimization failed for %s: %s", skill_type, exc)
        return False

    # Extract improved instruction from the optimized program
    try:
        new_instruction = optimized.generate.signature.instructions
    except AttributeError:
        logger.warning("Could not extract instructions from optimized program")
        return False

    if not new_instruction or new_instruction == active_prompt_text:
        logger.info("GEPA produced no improvement for %s", skill_type)
        return False

    # Save as a new candidate PromptVersion
    async with get_db_session() as db:
        new_version = PromptVersion(
            skill_type=skill_type,
            parent_id=active_prompt_id,
            prompt_text=new_instruction,
            status="candidate",
        )
        db.add(new_version)

    logger.info(
        "GEPA created new candidate prompt for %s (parent=%s)",
        skill_type, active_prompt_id,
    )
    return True

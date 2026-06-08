"""
Auto-generates PromptFoo YAML test cases from rejected generations.

Called as a FastAPI BackgroundTask when a reviewer rejects a generation:
    BackgroundTask(generate_test_case, generation_id=gen_id)

Also callable directly from the regression runner after bulk rejections:
    python -m ppt_agent.evals.test_case_generator --generation-id <uuid>

Each generated test case:
- Captures the slide input that caused the rejection
- Encodes the feedback signals as Tier-1 assertions (what must NOT happen again)
- Appends a llm-rubric assertion using the rejection reason
- Is appended to evals/regression_suite/auto_generated.yaml
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import textwrap
import uuid
from pathlib import Path

import anthropic

from ppt_agent.db.session import get_db_session

logger = logging.getLogger(__name__)

_AUTO_YAML = Path(__file__).parent / "regression_suite" / "auto_generated.yaml"

# ── Signal → deterministic assertion mapping ──────────────────────────────────

_SIGNAL_TO_ASSERTION: dict[str, dict] = {
    "too_long": {"type": "javascript", "value": "output.length < 8000", "metric": "max-length"},
    "too_short": {"type": "javascript", "value": "output.length > 800", "metric": "min-length"},
    "format_violation": {"type": "contains", "value": "<IndexList>", "metric": "format-check"},
    "missing_example": {"type": "javascript", "value": "(output.match(/<details>/g)||[]).length >= 3", "metric": "example-count"},
    "wrong_tone": {"type": "not-contains", "value": "As an AI language model", "metric": "tone-check"},
    "factual_error": None,          # no deterministic assertion — use rubric only
    "unnecessary_diagram": None,
    "needs_diagram": None,
    "unclear_explanation": {"type": "javascript", "value": "(output.match(/Explanation:/g)||[]).length >= 3", "metric": "explanation-count"},
}


# ── YAML helpers ──────────────────────────────────────────────────────────────

def _yaml_str(value: str, indent: int = 0) -> str:
    """Produce a YAML block scalar for multi-line strings or quoted single-line."""
    if "\n" in value or len(value) > 80:
        lines = value.splitlines()
        block = "\n".join("  " + l for l in lines)
        return f"|\n{block}"
    safe = value.replace('"', '\\"')
    return f'"{safe}"'


def _build_yaml_block(
    description: str,
    skill: str,
    slide_title: str,
    slide_body: str,
    assertions: list[dict],
) -> str:
    slide_body_safe = slide_body[:800].replace('"', '\\"').replace("\n", " ")
    lines = [
        f"- description: {_yaml_str(description)}",
        f"  vars:",
        f'    skill: "{skill}"',
        f'    slide_title: "{slide_title}"',
        f'    slide_body: "{slide_body_safe}"',
        f"  assert:",
    ]
    for a in assertions:
        lines.append(f"    - type: {a['type']}")
        val = str(a["value"]).replace('"', '\\"')
        lines.append(f'      value: "{val}"')
        if "metric" in a:
            lines.append(f'      metric: {a["metric"]}')
        if "threshold" in a:
            lines.append(f'      threshold: {a["threshold"]}')
    return "\n".join(lines) + "\n"


# ── LLM-assisted rubric generation ───────────────────────────────────────────

async def _generate_rubric_prompt(
    skill: str,
    slide_title: str,
    rejected_output: str,
    reviewer_notes: list[str],
    signals: list[str],
) -> str:
    """Ask Claude to write a targeted rubric assertion based on the rejection reason."""
    from ppt_agent.config.settings import settings

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    notes_text = "\n".join(f"- {n}" for n in reviewer_notes if n)
    signals_text = ", ".join(signals)

    system = textwrap.dedent("""
        You write PromptFoo llm-rubric assertion prompts.
        Given information about a rejected reading material output, write a rubric prompt
        that a future judge will use to detect the SAME class of failure.

        Rules:
        - Be specific to the failure — not generic
        - End with: Return SCORE: N/5 and a one-line reason
        - Maximum 4 sentences
        - Do NOT mention the specific rejected text
        - Output ONLY the rubric prompt text, nothing else
    """).strip()

    user = textwrap.dedent(f"""
        Skill: {skill}
        Slide title: {slide_title}
        Feedback signals: {signals_text}
        Reviewer notes:
        {notes_text or "(none)"}

        Rejected output excerpt (first 400 chars):
        {rejected_output[:400]}
    """).strip()

    response = await client.messages.create(
        model=settings.generation_model,
        max_tokens=256,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


# ── Main generator ────────────────────────────────────────────────────────────

async def generate_test_case(generation_id: str) -> None:
    """
    Fetch a rejected generation from the DB, build a YAML test case, and
    append it to auto_generated.yaml.
    """
    from sqlalchemy import select

    from ppt_agent.db.models import Feedback, Generation

    async with get_db_session() as db:
        gen = await db.get(Generation, uuid.UUID(generation_id))
        if gen is None:
            logger.error("Generation %s not found", generation_id)
            return

        feedbacks = (
            await db.execute(
                select(Feedback).where(Feedback.generation_id == gen.id)
            )
        ).scalars().all()

    if not feedbacks:
        logger.warning("No feedback for generation %s — skipping test case", generation_id)
        return

    signals = [f.signal_type for f in feedbacks]
    reviewer_notes = [f.reviewer_note for f in feedbacks if f.reviewer_note]
    skill = gen.skill_type

    # Rebuild slide info from the stored output (best effort — original slide not stored)
    slide_title = f"(from generation {generation_id[:8]})"
    slide_body = ""

    # Build assertions
    assertions: list[dict] = []
    for signal in signals:
        assertion = _SIGNAL_TO_ASSERTION.get(signal)
        if assertion:
            assertions.append(assertion)

    # Always add a rubric assertion derived from the rejection
    rubric_text = await _generate_rubric_prompt(
        skill=skill,
        slide_title=slide_title,
        rejected_output=gen.output_text or "",
        reviewer_notes=reviewer_notes,
        signals=signals,
    )
    assertions.append({
        "type": "llm-rubric",
        "value": rubric_text,
        "metric": "rubric-quality",
        "threshold": "0.7",
    })

    if not assertions:
        logger.info("No mappable assertions for signals %s — only rubric added", signals)

    description = (
        f"auto: {skill} — "
        + ", ".join(signals[:3])
        + (f" (gen={generation_id[:8]})")
    )

    yaml_block = _build_yaml_block(
        description=description,
        skill=skill,
        slide_title=slide_title,
        slide_body=slide_body,
        assertions=assertions,
    )

    # Append to file (thread-safe enough for single-writer background task)
    with _AUTO_YAML.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.write(yaml_block)

    logger.info(
        "Appended test case for generation %s (%s) to auto_generated.yaml",
        generation_id[:8], skill,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-id", required=True)
    args = parser.parse_args()

    asyncio.run(generate_test_case(args.generation_id))

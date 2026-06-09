"""
Deck compiler — ONE LLM call per deck upload.

Takes raw slide content (title + body text from every slide) plus any
developer-curated source passages and generates a single, comprehensive
reading material document.

Source passage budget:
  - Max 2,000 chars per passage (enforced at API + DB layer)
  - Max 12,000 chars total across all passages for one deck
  - Budget guard raises SourceBudgetExceeded before the LLM call
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from ppt_agent import llm
from ppt_agent.db.models import Generation, SourceContent
from ppt_agent.db.session import get_db_session
from ppt_agent.memory.prompt_store import get_active
from ppt_agent.skills.cost_tracker import _cost_usd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide

MAX_SOURCE_CHARS_PER_DECK = 12_000  # ~3,000 tokens — keeps total input ≤ 4,000 tokens


class SourceBudgetExceeded(Exception):
    pass


def check_source_budget(passages: list[SourceContent]) -> None:
    total = sum(len(p.passage_text) for p in passages)
    if total > MAX_SOURCE_CHARS_PER_DECK:
        raise SourceBudgetExceeded(
            f"Total source content ({total:,} chars) exceeds the "
            f"{MAX_SOURCE_CHARS_PER_DECK:,}-char limit (~3,000 tokens). "
            "Remove passages to continue."
        )


async def compile_deck(deck_id: str, slides: list[ParsedSlide]) -> str:
    """
    Generate ONE reading material for the whole deck.
    Returns the generation_id of the stored Generation row.
    """
    async with get_db_session() as db:
        prompt_version = await get_active("deck_reading", db)
        if prompt_version is None:
            raise RuntimeError("No active prompt for deck_reading — run reseed_prompts.py")

        # Fetch developer-curated source passages for this deck
        source_rows = (
            await db.execute(
                select(SourceContent)
                .where(SourceContent.deck_id == uuid.UUID(deck_id))
                .order_by(SourceContent.created_at.asc())
            )
        ).scalars().all()

        if source_rows:
            check_source_budget(list(source_rows))

        user_text = _build_user_text(slides, list(source_rows))

        output, tokens_in, tokens_out = await llm.complete(
            system=prompt_version.prompt_text,
            user=user_text,
            max_tokens=8192,
        )

        gen = Generation(
            deck_id=uuid.UUID(deck_id),
            skill_type="deck_reading",
            slide_index=-1,
            prompt_version_id=prompt_version.id,
            output_text=output,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            token_cost_usd=_cost_usd(tokens_in, tokens_out),
            status="pending",
            is_shadow=False,
        )
        db.add(gen)
        await db.flush()
        return str(gen.id)


def _build_user_text(slides: list[ParsedSlide], source_passages: list[SourceContent]) -> str:
    """
    Flatten all slide content into a single prompt block.
    Appends validated source passages as a grounding reference section.
    """
    lines: list[str] = [
        f"PRESENTATION CONTENT ({len(slides)} slides)\n",
        "Generate ONE complete reading material document for this entire presentation.\n",
    ]

    for slide in slides:
        title = slide.title or f"Slide {slide.slide_index}"
        body = (slide.body_text or "").strip()
        notes = (slide.speaker_notes or "").strip()
        has_images = len(slide.embedded_images) > 0

        lines.append(f"--- Slide {slide.slide_index}: {title} ---")
        if body:
            lines.append(body)
        if notes:
            lines.append(f"[Speaker notes: {notes}]")
        if has_images:
            lines.append(f"[This slide contains {len(slide.embedded_images)} image(s)]")
        lines.append("")

    if source_passages:
        lines.append("\n--- REFERENCE PASSAGES (verified, use as grounding source) ---\n")
        for p in source_passages:
            ref = f"{p.source_title or 'Reference'}"
            if p.page_ref:
                ref += f", p.{p.page_ref}"
            lines.append(f"[{p.topic_label}] {ref}:")
            lines.append(p.passage_text)
            lines.append("")

    return "\n".join(lines)

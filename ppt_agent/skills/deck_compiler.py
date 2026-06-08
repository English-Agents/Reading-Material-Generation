"""
Deck compiler — ONE LLM call per deck upload.

Takes raw slide content (title + body text from every slide) and generates
a single, comprehensive reading material document.  No per-slide generation.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from ppt_agent import llm
from ppt_agent.db.models import Generation
from ppt_agent.db.session import get_db_session
from ppt_agent.memory.prompt_store import get_active
from ppt_agent.skills.cost_tracker import _cost_usd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide


async def compile_deck(deck_id: str, slides: list[ParsedSlide]) -> str:
    """
    Generate ONE reading material for the whole deck.
    Returns the generation_id of the stored Generation row.
    """
    async with get_db_session() as db:
        prompt_version = await get_active("deck_reading", db)
        if prompt_version is None:
            raise RuntimeError("No active prompt for deck_reading — run reseed_prompts.py")

        user_text = _build_user_text(slides)

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


def _build_user_text(slides: list[ParsedSlide]) -> str:
    """
    Flatten all slide content into a single prompt block.
    Images are noted but not inlined — keeps the call text-only and cheap.
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

    return "\n".join(lines)

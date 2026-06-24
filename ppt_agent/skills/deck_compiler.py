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

import logging
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

MAX_SOURCE_CHARS_PER_DECK = 12_000  # default; runtime value comes from settings

from ppt_agent.config.settings import settings as _settings  # noqa: E402


class SourceBudgetExceeded(Exception):
    pass


def check_source_budget(passages: list[SourceContent]) -> None:
    limit = _settings.max_source_chars_per_deck
    total = sum(len(p.passage_text) for p in passages)
    if total > limit:
        raise SourceBudgetExceeded(
            f"Total source content ({total:,} chars) exceeds the "
            f"{limit:,}-char limit (~3,000 tokens). "
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

        book_chunks = []
        if not source_rows and _settings.use_book_retrieval:
            # No manual passages — try to retrieve from ingested books
            topic_labels = [s.title for s in slides if s.title]
            from ppt_agent.skills.book_retriever import retrieve_for_topics
            book_chunks = await retrieve_for_topics(topic_labels, db)

        if source_rows:
            check_source_budget(list(source_rows))

        user_text = _build_user_text(slides, list(source_rows), book_chunks)

        output, tokens_in, tokens_out, truncated = await llm.complete(
            system=prompt_version.prompt_text,
            user=user_text,
            max_tokens=16000,
        )

        if truncated:
            # Large multi-topic decks can still exceed 16k tokens with the
            # full instructional format — retry once with a much higher budget
            # instead of silently storing a cut-off document.
            logging.getLogger(__name__).warning(
                "deck_compiler: output truncated at 16000 tokens for deck %s — retrying with 32000",
                deck_id,
            )
            output, tokens_in, tokens_out, truncated = await llm.complete(
                system=prompt_version.prompt_text,
                user=user_text,
                max_tokens=32000,
            )
            if truncated:
                logging.getLogger(__name__).warning(
                    "deck_compiler: output still truncated at 32000 tokens for deck %s — "
                    "deck likely has too many topics for one document",
                    deck_id,
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


def _build_user_text(slides: list[ParsedSlide], source_passages: list[SourceContent], book_chunks: list | None = None) -> str:
    """
    Build the LLM prompt.

    Only slide TITLES are extracted — body text is intentionally excluded so the
    LLM cannot quote or paraphrase raw PPT content. All factual content must come
    from the curated REFERENCE PASSAGES block below.
    """
    topic_labels = []
    for slide in slides:
        title = (slide.title or f"Slide {slide.slide_index}").strip()
        if title:
            topic_labels.append(f"  {slide.slide_index}. {title}")

    lines: list[str] = [
        f"TOPIC OUTLINE ({len(slides)} slides — titles only, no body text):\n",
    ] + topic_labels + [""]

    if source_passages:
        lines += [
            "Generate ONE complete reading material document covering ALL topics above.",
            "Base ALL factual content EXCLUSIVELY on the REFERENCE PASSAGES provided below.",
            "Do NOT invent facts not present in the reference passages.",
            "",
            "--- REFERENCE PASSAGES (curated source material — sole factual basis) ---\n",
        ]
        for p in source_passages:
            ref = p.source_title or "Reference"
            if p.page_ref:
                ref += f", p.{p.page_ref}"
            if p.author:
                ref += f" ({p.author})"
            lines.append(f"[{p.topic_label}] {ref}:")
            lines.append(p.passage_text)
            lines.append("")
    elif book_chunks:
        lines += [
            "Generate ONE complete reading material document covering ALL topics above.",
            "Base ALL factual content EXCLUSIVELY on the REFERENCE PASSAGES provided below.",
            "Do NOT invent facts not present in the reference passages.",
            "",
            "--- REFERENCE PASSAGES (auto-retrieved from book library) ---\n",
        ]
        for chunk in book_chunks:
            ref = chunk.book_title
            if chunk.author:
                ref += f" by {chunk.author}"
            if chunk.chapter:
                ref += f" — {chunk.chapter}"
            lines.append(f"[{ref}]:")
            lines.append(chunk.chunk_text)
            lines.append("")
    else:
        lines.append(
            "Generate ONE complete reading material document covering ALL topics listed above.\n"
            "No reference passages have been provided — use your training knowledge.\n"
            "Cover every topic in the outline thoroughly. Do not skip any."
        )

    return "\n".join(lines)

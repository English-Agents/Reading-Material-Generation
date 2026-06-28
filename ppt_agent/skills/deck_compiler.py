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

import json
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
from ppt_agent.skills.topic_coverage_validator import validate_topic_coverage

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide

MAX_SOURCE_CHARS_PER_DECK = 12_000  # default; runtime value comes from settings

from ppt_agent.config.settings import settings as _settings  # noqa: E402

logger = logging.getLogger(__name__)


class SourceBudgetExceeded(Exception):
    pass


class NoTopicsExtracted(Exception):
    """Raised when no slide produced a usable title — generation would be meaningless."""
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

        # Persisted so a human (or this validator) can later check what the
        # document was actually supposed to cover — previously this was
        # discarded after the LLM call, making input/output drift invisible.
        topic_outline = [s.title.strip() for s in slides if s.title and s.title.strip()]

        # Guard: if the parser extracted no real titles, the LLM would only
        # receive "Slide 0..N" placeholders and produce an off-topic document.
        # Fail loudly instead of burning a generation on meaningless input.
        if not topic_outline:
            raise NoTopicsExtracted(
                f"No slide titles could be extracted from this deck ({len(slides)} slides). "
                "The file may use images-only slides, or an unsupported layout. "
                "Add source passages manually, or upload a deck with text titles."
            )

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
            logger.warning(
                "deck_compiler: output truncated at 16000 tokens for deck %s — retrying with 32000",
                deck_id,
            )
            output, tokens_in, tokens_out, truncated = await llm.complete(
                system=prompt_version.prompt_text,
                user=user_text,
                max_tokens=32000,
            )
            if truncated:
                logger.warning(
                    "deck_compiler: output still truncated at 32000 tokens for deck %s — "
                    "deck likely has too many topics for one document",
                    deck_id,
                )

        # Topic coverage check — catches the case where the document drifts
        # away from what the input slides actually asked for. On a clear
        # mismatch, regenerate once with the missing topics called out
        # explicitly instead of silently shipping an off-topic document.
        coverage = await validate_topic_coverage(topic_outline, output)

        if coverage.verdict == "fail":
            logger.warning(
                "deck_compiler: topic coverage FAILED for deck %s (score=%.2f, missing=%s) — regenerating once",
                deck_id, coverage.coverage_score, coverage.missing_topics,
            )
            correction_text = (
                user_text
                + "\n\n--- CORRECTION REQUIRED ---\n"
                + "Your previous attempt did not substantively cover these required topics: "
                + ", ".join(coverage.missing_topics or topic_outline)
                + ". Rewrite the document end to end so that EVERY topic in the outline above "
                + "gets a real, substantive section — not just a passing mention."
            )
            retry_output, retry_tokens_in, retry_tokens_out, retry_truncated = await llm.complete(
                system=prompt_version.prompt_text,
                user=correction_text,
                max_tokens=32000,
            )
            if not retry_truncated:
                output = retry_output
                tokens_in += retry_tokens_in
                tokens_out += retry_tokens_out
                coverage = await validate_topic_coverage(topic_outline, output)

        gen = Generation(
            deck_id=uuid.UUID(deck_id),
            skill_type="deck_reading",
            slide_index=-1,
            prompt_version_id=prompt_version.id,
            output_text=output,
            topic_outline=json.dumps(topic_outline),
            topic_coverage_score=coverage.coverage_score,
            topic_coverage_verdict=coverage.verdict,
            topic_coverage_reason=coverage.reason,
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
        # No curated passages and no book retrieval. Use the slide body text
        # itself as grounding so the reading material reflects what the deck
        # actually teaches — not just a generic essay on the titles. This is
        # what makes the output match the student's input deck.
        slide_content_blocks = []
        total_chars = 0
        max_chars = 30_000   # keep the grounding block within prompt budget
        for slide in slides:
            body = (slide.body_text or "").strip()
            notes = (slide.speaker_notes or "").strip()
            label = (slide.title or f"Slide {slide.slide_index}").strip()
            block = f"[Slide {slide.slide_index} — {label}]"
            if body:
                block += f"\n{body}"
            if notes:
                block += f"\nNotes: {notes}"
            if body or notes:
                if total_chars + len(block) > max_chars:
                    break
                slide_content_blocks.append(block)
                total_chars += len(block)

        if slide_content_blocks:
            lines += [
                "Generate ONE complete reading material document covering ALL topics above.",
                "Base the document on the SLIDE CONTENT below — this is what the",
                "presentation actually teaches. Expand, explain, and structure this content",
                "into proper instructional reading material. You MAY add clarifying detail",
                "and examples from your knowledge, but every topic the slides cover must be",
                "covered, and you must not contradict the slide content.",
                "",
                "FAITHFULNESS REQUIREMENTS — the document must teach the way the deck teaches:",
                "1. PRACTICE QUESTIONS: If the slides contain practice items (e.g. 'choose the",
                "   correct verb', fill-in-the-blank, Person A/B activities, speaking exercises),",
                "   you MUST include a Practice section that reuses or closely mirrors those exact",
                "   questions, with the correct answer and a one-line reason for each. Do not drop them.",
                "2. METHODOLOGY: If the slides present a method, process, framework, or funnel for",
                "   solving the problem, you MUST include it as its own section — it is core teaching,",
                "   not decoration.",
                "3. FOUNDATIONAL TABLES: Reproduce any foundational reference tables the slides show",
                "   (verb-form charts, positive/negative paradigms, classification lists) as markdown tables.",
                "4. STAY IN SCOPE: Cover what the deck covers. Do not introduce major new topics or",
                "   scenarios the deck never mentions — enrichment is fine only as brief clarification.",
                "",
                "--- SLIDE CONTENT (the actual presentation — basis for the document) ---\n",
            ] + slide_content_blocks
        else:
            # Slides truly have no extractable body text (image-only deck).
            lines.append(
                "Generate ONE complete reading material document covering ALL topics listed above.\n"
                "No slide body text was available — use your training knowledge.\n"
                "Cover every topic in the outline thoroughly. Do not skip any."
            )

    return "\n".join(lines)

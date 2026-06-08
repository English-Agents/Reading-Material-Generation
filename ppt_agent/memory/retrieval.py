"""
retrieval.py — build MemoryContext for a slide before skill execution.

Steps:
  1. embed_slide: call OpenAI text-embedding-3-small on slide text
  2. get_similar_generations: pgvector top-5 cosine similarity search
  3. get_active_patterns: active learned rules for the skill
  4. get_reviewer_prefs: top-N aggregated feedback signals
  5. Return MemoryContext (passed read-only into every skill run())
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ppt_agent.config.settings import settings
from ppt_agent.memory.feedback_store import get_reviewer_prefs
from ppt_agent.memory.generation_store import get_similar_generations
from ppt_agent.memory.pattern_store import get_active_patterns
from ppt_agent.memory.types import EMPTY_CONTEXT, MemoryContext

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Module-level OpenAI client — lazy init on first call
_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.AsyncOpenAI()
    return _openai_client


async def embed_text(text: str) -> np.ndarray:
    """
    Call OpenAI text-embedding-3-small and return a (1536,) float32 ndarray.
    Truncates input to 8000 chars to stay within token limits.
    """
    client = _get_openai_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text[:8000],
    )
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    return vec


def _slide_to_text(slide: ParsedSlide) -> str:
    parts = []
    if slide.title:
        parts.append(slide.title)
    if slide.body_text:
        parts.append(slide.body_text)
    if slide.speaker_notes:
        parts.append(slide.speaker_notes)
    return "\n".join(parts)


async def retrieve_context(
    slide: ParsedSlide,
    skill_type: str,
    db: "AsyncSession",
) -> MemoryContext:
    """
    Build a MemoryContext for one slide + skill_type combination.
    Returns EMPTY_CONTEXT on any error so the skill still runs.
    """
    try:
        slide_text = _slide_to_text(slide)
        if not slide_text.strip():
            return EMPTY_CONTEXT

        embedding = await embed_text(slide_text)

        similar, patterns, prefs = await _gather(embedding, skill_type, db)

        return MemoryContext(
            similar_outputs=similar,
            active_patterns=patterns,
            reviewer_prefs=prefs,
        )

    except Exception as exc:
        logger.warning(
            "retrieve_context failed for skill=%s slide=%d: %s — using empty context",
            skill_type, slide.slide_index, exc,
        )
        return EMPTY_CONTEXT


async def _gather(embedding: np.ndarray, skill_type: str, db: "AsyncSession"):
    """Fan-out the three memory queries concurrently."""
    import asyncio

    similar_task = asyncio.create_task(
        get_similar_generations(embedding, skill_type, db, k=5)
    )
    patterns_task = asyncio.create_task(
        get_active_patterns(skill_type, db)
    )
    prefs_task = asyncio.create_task(
        get_reviewer_prefs(skill_type, db, top_n=5)
    )

    similar = await similar_task
    patterns = await patterns_task
    prefs = await prefs_task

    return similar, patterns, prefs


async def embed_deck_slides(slides: list[ParsedSlide]) -> np.ndarray:
    """
    Embed the concatenated text of all slides in a deck.
    Used for deck-level similarity (not per-slide).
    """
    combined = "\n\n".join(_slide_to_text(s) for s in slides)
    return await embed_text(combined)

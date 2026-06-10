"""
Book retriever — finds relevant chunks from ingested books for a given set of topic labels.

Usage:
  chunks = await retrieve_for_topics(["Active Voice", "Passive Voice"], db)
  # Returns list of BookChunkResult sorted by relevance score

Requires:
  - books/ folder populated and ingest_books.py already run
  - OPENAI_API_KEY set (for text-embedding-3-small)
  - USE_BOOK_RETRIEVAL=true in .env
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ppt_agent.config.settings import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class BookChunkResult:
    book_title: str
    author: str | None
    chapter: str | None
    chunk_text: str
    similarity: float


async def retrieve_for_topics(
    topic_labels: list[str],
    db: "AsyncSession",
    top_k: int | None = None,
    min_similarity: float = 0.35,
) -> list[BookChunkResult]:
    """
    Embed the combined topic labels and return the top_k most similar book chunks.
    Returns empty list if no books have been ingested or embeddings are unavailable.
    """
    if not topic_labels:
        return []

    k = top_k or settings.book_retrieval_top_k

    try:
        from ppt_agent.memory.retrieval import embed_text
        from ppt_agent.db.models import BookChunk
        from sqlalchemy import select, func

        # Check if any chunks exist
        count = (await db.execute(select(func.count(BookChunk.id)))).scalar() or 0
        if count == 0:
            logger.info("book_retriever: no chunks in DB — skipping retrieval")
            return []

        # Embed the combined topic query
        query_text = " | ".join(topic_labels)
        query_vec = await embed_text(query_text)

        # pgvector cosine similarity search
        rows = (
            await db.execute(
                select(
                    BookChunk,
                    (1 - BookChunk.embedding.cosine_distance(query_vec.tolist())).label("similarity"),
                )
                .where(BookChunk.embedding.is_not(None))
                .order_by(BookChunk.embedding.cosine_distance(query_vec.tolist()))
                .limit(k * 3)   # fetch more, then filter by min_similarity
            )
        ).all()

        results = []
        total_chars = 0
        budget = settings.max_source_chars_per_deck

        for row, similarity in rows:
            if similarity < min_similarity:
                continue
            chunk_len = len(row.chunk_text)
            if total_chars + chunk_len > budget:
                break
            results.append(BookChunkResult(
                book_title=row.book_title,
                author=row.author,
                chapter=row.chapter,
                chunk_text=row.chunk_text,
                similarity=float(similarity),
            ))
            total_chars += chunk_len
            if len(results) >= k:
                break

        logger.info(
            "book_retriever: retrieved %d chunks (%.0f chars) for topics: %s",
            len(results), total_chars, query_text[:80],
        )
        return results

    except Exception as exc:
        logger.warning("book_retriever failed: %s — proceeding without book context", exc)
        return []

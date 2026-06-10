"""
Book ingestion pipeline — run this whenever you add new books to the books/ folder.

Supported formats: PDF (.pdf), EPUB (.epub), plain text (.txt), Markdown (.md)

Usage:
    python ingest_books.py                    # process all new files in books/
    python ingest_books.py --reindex          # re-process all files (clears existing)
    python ingest_books.py --file my_book.pdf # process one specific file
    python ingest_books.py --list             # show what's already indexed

What it does:
    1. Extracts full text from each book
    2. Splits into ~1500-char chunks (at sentence boundaries)
    3. Generates embeddings via OpenAI text-embedding-3-small
    4. Stores in the book_chunks table for vector similarity search

After ingesting, set USE_BOOK_RETRIEVAL=true in .env to enable auto-retrieval.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOOKS_DIR = Path(__file__).parent / "books"
CHUNK_SIZE = 1500       # target chars per chunk
CHUNK_OVERLAP = 150     # overlap between chunks to preserve context


# ── Text extractors ───────────────────────────────────────────────────────────

def extract_pdf(path: Path) -> list[tuple[str, str]]:
    """Returns list of (chapter_label, text) tuples — one per page group."""
    import pdfplumber

    pages_text: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                pages_text.append((f"Page {i + 1}", text))

    return pages_text


def extract_epub(path: Path) -> list[tuple[str, str]]:
    """Returns list of (chapter_label, text) tuples — one per EPUB section."""
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    sections: list[tuple[str, str]] = []

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Try to get a chapter title from H1/H2
        heading = soup.find(["h1", "h2", "h3"])
        chapter = heading.get_text(strip=True) if heading else item.get_name()

        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 100:
            sections.append((chapter, text))

    return sections


def extract_txt(path: Path) -> list[tuple[str, str]]:
    """Returns a single (filename, full_text) tuple."""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [(path.stem, text)]


def extract_text(path: Path) -> list[tuple[str, str]]:
    """Dispatch to the right extractor based on extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    elif suffix == ".epub":
        return extract_epub(path)
    elif suffix in (".txt", ".md"):
        return extract_txt(path)
    else:
        logger.warning("Unsupported format: %s — skipping", path.name)
        return []


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks at sentence boundaries.
    Tries to keep each chunk close to chunk_size chars.
    """
    # Normalise whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    # Split into sentences (period/exclamation/question + space or newline)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip() if current else sentence
        else:
            if current:
                chunks.append(current.strip())
            # Start new chunk with overlap from end of previous
            if overlap and current:
                overlap_text = current[-overlap:]
                current = f"{overlap_text} {sentence}".strip()
            else:
                current = sentence

    if current.strip():
        chunks.append(current.strip())

    # Filter out very short chunks (likely headers/noise)
    return [c for c in chunks if len(c) >= 100]


# ── Embedding + DB ────────────────────────────────────────────────────────────

async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Embed a list of text chunks using OpenAI text-embedding-3-small."""
    from ppt_agent.memory.retrieval import embed_text
    embeddings = []
    for i, chunk in enumerate(chunks):
        vec = await embed_text(chunk)
        embeddings.append(vec.tolist())
        if (i + 1) % 20 == 0:
            logger.info("  Embedded %d / %d chunks…", i + 1, len(chunks))
    return embeddings


async def store_chunks(
    db,
    file_name: str,
    book_title: str,
    author: str | None,
    chapter: str,
    chunks: list[str],
    embeddings: list[list[float]],
    start_index: int = 0,
) -> int:
    """Insert BookChunk rows. Returns number of rows inserted."""
    from ppt_agent.db.models import BookChunk
    count = 0
    for i, (text, vec) in enumerate(zip(chunks, embeddings)):
        db.add(BookChunk(
            book_title=book_title,
            author=author,
            file_name=file_name,
            chapter=chapter or None,
            chunk_text=text,
            chunk_index=start_index + i,
            embedding=vec,
        ))
        count += 1
    return count


async def delete_existing(db, file_name: str) -> None:
    from sqlalchemy import delete
    from ppt_agent.db.models import BookChunk
    await db.execute(delete(BookChunk).where(BookChunk.file_name == file_name))


async def count_existing(db, file_name: str) -> int:
    from sqlalchemy import select, func
    from ppt_agent.db.models import BookChunk
    return (
        await db.execute(
            select(func.count(BookChunk.id)).where(BookChunk.file_name == file_name)
        )
    ).scalar() or 0


# ── Metadata helpers ──────────────────────────────────────────────────────────

def guess_metadata(path: Path) -> tuple[str, str | None]:
    """
    Try to extract book_title and author from the filename.
    Convention: "Title - Author.pdf" or "Title.pdf"
    Returns (book_title, author_or_None).
    """
    stem = path.stem
    if " - " in stem:
        parts = stem.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return stem.strip(), None


# ── Main ──────────────────────────────────────────────────────────────────────

async def process_file(path: Path, db, reindex: bool = False) -> int:
    """Process one book file. Returns number of chunks stored."""
    file_name = path.name
    book_title, author = guess_metadata(path)

    # Skip if already indexed (unless reindexing)
    existing = await count_existing(db, file_name)
    if existing > 0 and not reindex:
        logger.info("SKIP  %s — already indexed (%d chunks)", file_name, existing)
        return 0

    if reindex and existing > 0:
        logger.info("CLEAR %s — removing %d existing chunks", file_name, existing)
        await delete_existing(db, file_name)

    logger.info("READ  %s", file_name)
    sections = extract_text(path)
    if not sections:
        logger.warning("  No text extracted from %s", file_name)
        return 0

    total = 0
    chunk_index = 0

    for chapter, section_text in sections:
        chunks = chunk_text(section_text)
        if not chunks:
            continue

        logger.info("  Chapter: %s — %d chunks", chapter[:60], len(chunks))

        embeddings = await embed_chunks(chunks)
        stored = await store_chunks(
            db, file_name, book_title, author, chapter,
            chunks, embeddings, start_index=chunk_index,
        )
        total += stored
        chunk_index += stored

    return total


async def list_indexed(db) -> None:
    from sqlalchemy import select, func
    from ppt_agent.db.models import BookChunk

    rows = (
        await db.execute(
            select(
                BookChunk.file_name,
                BookChunk.book_title,
                BookChunk.author,
                func.count(BookChunk.id).label("chunks"),
            )
            .group_by(BookChunk.file_name, BookChunk.book_title, BookChunk.author)
            .order_by(BookChunk.book_title)
        )
    ).all()

    if not rows:
        print("No books indexed yet. Drop files into the books/ folder and run again.")
        return

    print(f"\n{'Book':<40} {'Author':<25} {'File':<35} {'Chunks':>6}")
    print("─" * 110)
    for r in rows:
        print(f"{r.book_title[:39]:<40} {(r.author or '—')[:24]:<25} {r.file_name[:34]:<35} {r.chunks:>6}")
    print()


async def main(args: argparse.Namespace) -> None:
    from ppt_agent.db.session import get_db_session

    if not BOOKS_DIR.exists():
        logger.error("books/ folder not found at %s", BOOKS_DIR)
        sys.exit(1)

    async with get_db_session() as db:

        if args.list:
            await list_indexed(db)
            return

        # Determine which files to process
        if args.file:
            target = BOOKS_DIR / args.file
            if not target.exists():
                logger.error("File not found: %s", target)
                sys.exit(1)
            files = [target]
        else:
            files = [
                p for p in sorted(BOOKS_DIR.iterdir())
                if p.suffix.lower() in (".pdf", ".epub", ".txt", ".md")
            ]

        if not files:
            print("No supported files found in books/. Add .pdf, .epub, or .txt files.")
            return

        print(f"\nFound {len(files)} file(s) in books/\n")
        grand_total = 0

        for path in files:
            count = await process_file(path, db, reindex=args.reindex)
            if count:
                logger.info("DONE  %s — %d chunks stored", path.name, count)
                grand_total += count

        if grand_total:
            print(f"\n✓ Ingestion complete — {grand_total} chunks stored total.")
            print("  Set USE_BOOK_RETRIEVAL=true in your .env to enable auto-retrieval.")
        else:
            print("\nAll files already indexed. Use --reindex to force re-processing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest books into the book_chunks table")
    parser.add_argument("--reindex", action="store_true", help="Re-process already-indexed files")
    parser.add_argument("--file", default=None, help="Process a single file by name (e.g. grammar.pdf)")
    parser.add_argument("--list", action="store_true", help="List already-indexed books")
    args = parser.parse_args()
    asyncio.run(main(args))

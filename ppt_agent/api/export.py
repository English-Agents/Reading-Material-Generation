"""
Export API — convert approved reading material to various formats.

Routes:
  POST /export/{deck_id}   — body: {"format": "markdown"|"pdf"|"docx"}

All approved generations for the deck are concatenated in slide order,
then converted via pypandoc (pdf/docx) or returned as markdown directly.
Notion is explicitly out of scope — returns 501.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from ppt_agent.api.deps import get_db
from ppt_agent.db.models import Generation
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]

ExportFormat = Literal["markdown", "pdf", "docx", "notion"]


class ExportRequest(BaseModel):
    format: ExportFormat = "markdown"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_approved_outputs(deck_id: str, db: AsyncSession) -> list[str]:
    """Return approved output texts in slide_index order."""
    rows = (
        await db.execute(
            select(Generation.slide_index, Generation.output_text)
            .where(
                Generation.deck_id == deck_id,
                Generation.status == "approved",
                Generation.is_shadow == False,
            )
            .order_by(Generation.slide_index.asc())
        )
    ).all()
    return [row.output_text for row in rows if row.output_text]


def _concatenate(outputs: list[str]) -> str:
    return "\n\n---\n\n".join(outputs)


def _to_pdf(markdown_text: str) -> bytes:
    try:
        import pypandoc
        return pypandoc.convert_text(
            markdown_text,
            "pdf",
            format="markdown",
            extra_args=["--pdf-engine=xelatex"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"PDF conversion failed: {exc}. Ensure pandoc + xelatex are installed.",
        )


def _to_docx(markdown_text: str) -> bytes:
    try:
        import io
        import tempfile
        import pypandoc

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp_path = tmp.name

        pypandoc.convert_text(
            markdown_text,
            "docx",
            format="markdown",
            outputfile=tmp_path,
        )
        with open(tmp_path, "rb") as f:
            return f.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"DOCX conversion failed: {exc}. Ensure pandoc is installed.",
        )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/{deck_id}")
async def export_deck(
    deck_id: str,
    body: ExportRequest,
    db: DB,
):
    if body.format == "notion":
        raise HTTPException(status_code=501, detail="Notion export is not implemented.")

    outputs = await _fetch_approved_outputs(deck_id, db)
    if not outputs:
        raise HTTPException(
            status_code=404,
            detail=f"No approved generations found for deck {deck_id}.",
        )

    markdown = _concatenate(outputs)

    if body.format == "markdown":
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="deck-{deck_id[:8]}.md"'},
        )

    if body.format == "pdf":
        pdf_bytes = _to_pdf(markdown)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="deck-{deck_id[:8]}.pdf"'},
        )

    if body.format == "docx":
        docx_bytes = _to_docx(markdown)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="deck-{deck_id[:8]}.docx"'},
        )

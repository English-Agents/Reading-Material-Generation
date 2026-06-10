"""Add book_chunks table for local book ingestion and retrieval

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "book_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_title", sa.Text, nullable=False),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("chapter", sa.Text, nullable=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_book_chunks_file_name", "book_chunks", ["file_name"])


def downgrade() -> None:
    op.drop_index("ix_book_chunks_file_name", "book_chunks")
    op.drop_table("book_chunks")

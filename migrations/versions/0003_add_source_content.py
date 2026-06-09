"""Add source_content table for developer-curated reference passages

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_content",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("deck_id", UUID(as_uuid=True), nullable=False),
        sa.Column("topic_label", sa.Text, nullable=False),
        sa.Column("source_title", sa.Text, nullable=True),
        sa.Column("page_ref", sa.Text, nullable=True),
        sa.Column("passage_text", sa.String(2000), nullable=False),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("uploaded_by", sa.Text, nullable=True),
        sa.Column("alignment_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("alignment_verdict", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_source_content_deck_id", "source_content", ["deck_id"])


def downgrade() -> None:
    op.drop_index("ix_source_content_deck_id", "source_content")
    op.drop_table("source_content")

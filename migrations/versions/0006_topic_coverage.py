"""Add topic coverage tracking to generations — detect input/output topic mismatch

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("topic_outline", sa.Text, nullable=True))
    op.add_column("generations", sa.Column("topic_coverage_score", sa.Numeric(4, 3), nullable=True))
    op.add_column("generations", sa.Column("topic_coverage_verdict", sa.Text, nullable=True))
    op.add_column("generations", sa.Column("topic_coverage_reason", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "topic_coverage_reason")
    op.drop_column("generations", "topic_coverage_verdict")
    op.drop_column("generations", "topic_coverage_score")
    op.drop_column("generations", "topic_outline")

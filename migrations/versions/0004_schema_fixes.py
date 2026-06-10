"""Schema fixes: alignment_reason column + expanded feedback signal types

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add alignment_reason to source_content
    op.add_column(
        "source_content",
        sa.Column("alignment_reason", sa.Text, nullable=True),
    )

    # Expand feedback.signal_type CHECK constraint to include 4 new signal types
    op.drop_constraint("ck_feedback_signal_type", "feedback", type_="check")
    op.create_check_constraint(
        "ck_feedback_signal_type",
        "feedback",
        "signal_type IN ("
        "'too_long','too_short','wrong_tone','missing_example',"
        "'factual_error','format_violation','unnecessary_diagram',"
        "'needs_diagram','unclear_explanation','wrong_difficulty_level',"
        "'missing_common_errors','missing_correction','diagram_incorrect'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_feedback_signal_type", "feedback", type_="check")
    op.create_check_constraint(
        "ck_feedback_signal_type",
        "feedback",
        "signal_type IN ("
        "'too_long','too_short','wrong_tone','missing_example',"
        "'factual_error','format_violation','unnecessary_diagram',"
        "'needs_diagram','unclear_explanation'"
        ")",
    )
    op.drop_column("source_content", "alignment_reason")

"""Add deck_reading to generations.skill_type CHECK constraint

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_generations_skill_type", "generations")
    op.create_check_constraint(
        "ck_generations_skill_type",
        "generations",
        "skill_type IN ('concept_explainer','code_walkthrough','diagram_describer',"
        "'figure_caption','quiz_generator','deck_reading')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_generations_skill_type", "generations")
    op.create_check_constraint(
        "ck_generations_skill_type",
        "generations",
        "skill_type IN ('concept_explainer','code_walkthrough','diagram_describer',"
        "'figure_caption','quiz_generator')",
    )

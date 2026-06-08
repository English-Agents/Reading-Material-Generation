"""Initial schema: generations, prompt_versions, repair_queue, feedback, pattern_memory, alerts

Revision ID: 0001
Revises:
Create Date: 2026-06-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # prompt_versions (no FK deps — create first)
    op.create_table(
        "prompt_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("skill_type", sa.Text, nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="candidate"),
        sa.Column("pass_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("avg_rubric_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retired_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('candidate','shadow','active','retired')",
            name="ck_prompt_versions_status",
        ),
    )

    # generations
    op.create_table(
        "generations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("deck_id", UUID(as_uuid=True), nullable=True),
        sa.Column("deck_url", sa.Text, nullable=True),
        sa.Column("skill_type", sa.Text, nullable=False),
        sa.Column("slide_index", sa.Integer, nullable=False),
        sa.Column("prompt_version_id", UUID(as_uuid=True), sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("output_text", sa.Text, nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("token_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("eval_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_shadow", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint(
            "skill_type IN ('concept_explainer','code_walkthrough','diagram_describer','figure_caption','quiz_generator')",
            name="ck_generations_skill_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','needs_repair')",
            name="ck_generations_status",
        ),
    )

    # IVFFlat index for cosine similarity search on embeddings
    op.execute(
        "CREATE INDEX ON generations USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # repair_queue
    op.create_table(
        "repair_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("generation_id", UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','in_progress','resolved')",
            name="ck_repair_queue_status",
        ),
    )

    # feedback
    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("generation_id", UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.Text, nullable=True),
        sa.Column("reviewer_id", sa.Text, nullable=True),
        sa.Column("signal_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Integer, nullable=False),
        sa.Column("reviewer_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint(
            "signal_type IN ('too_long','too_short','wrong_tone','missing_example',"
            "'factual_error','format_violation','unnecessary_diagram',"
            "'needs_diagram','unclear_explanation')",
            name="ck_feedback_signal_type",
        ),
        sa.CheckConstraint("severity IN (1,2,3)", name="ck_feedback_severity"),
    )

    # pattern_memory
    op.create_table(
        "pattern_memory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("skill_type", sa.Text, nullable=False),
        sa.Column("pattern_text", sa.Text, nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("example_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False, server_default="candidate"),
        sa.Column("source_feedback_ids", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate','active','retired')",
            name="ck_pattern_memory_status",
        ),
    )

    # alerts
    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("alert_type", sa.Text, nullable=False),
        sa.Column("skill_type", sa.Text, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint(
            "alert_type IN ('score_drop','repair_queue_depth','repair_queue_age')",
            name="ck_alerts_alert_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("pattern_memory")
    op.drop_table("feedback")
    op.drop_table("repair_queue")
    op.drop_table("generations")
    op.drop_table("prompt_versions")
    op.execute('DROP EXTENSION IF EXISTS "vector"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')

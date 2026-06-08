import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    TIMESTAMP,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','shadow','active','retired')",
            name="ck_prompt_versions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    skill_type: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="candidate")
    pass_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    avg_rubric_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )
    promoted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    parent: Mapped[Optional["PromptVersion"]] = relationship(
        "PromptVersion", remote_side="PromptVersion.id", foreign_keys=[parent_id]
    )
    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="prompt_version"
    )


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = (
        CheckConstraint(
            "skill_type IN ('concept_explainer','code_walkthrough','diagram_describer','figure_caption','quiz_generator')",
            name="ck_generations_skill_type",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','needs_repair')",
            name="ck_generations_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deck_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    deck_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skill_type: Mapped[str] = mapped_column(Text, nullable=False)
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    eval_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )

    prompt_version: Mapped[Optional[PromptVersion]] = relationship(
        "PromptVersion", back_populates="generations"
    )
    repair_queue_entry: Mapped[Optional["RepairQueue"]] = relationship(
        "RepairQueue", back_populates="generation", uselist=False
    )
    feedback_entries: Mapped[list["Feedback"]] = relationship(
        "Feedback", back_populates="generation"
    )


class RepairQueue(Base):
    __tablename__ = "repair_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','resolved')",
            name="ck_repair_queue_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    generation: Mapped[Generation] = relationship(
        "Generation", back_populates="repair_queue_entry"
    )


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('too_long','too_short','wrong_tone','missing_example',"
            "'factual_error','format_violation','unnecessary_diagram',"
            "'needs_diagram','unclear_explanation')",
            name="ck_feedback_signal_type",
        ),
        CheckConstraint("severity IN (1,2,3)", name="ck_feedback_severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )

    generation: Mapped[Generation] = relationship("Generation", back_populates="feedback_entries")


class PatternMemory(Base):
    __tablename__ = "pattern_memory"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','active','retired')",
            name="ck_pattern_memory_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    skill_type: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3), nullable=True)
    example_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="candidate")
    source_feedback_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('score_drop','repair_queue_depth','repair_queue_age')",
            name="ck_alerts_alert_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    alert_type: Mapped[str] = mapped_column(Text, nullable=False)
    skill_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )

"""
Shared data contracts for the memory layer.
MemoryContext is constructed by memory/retrieval.py (Phase 5).
Skills receive it as a read-only snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SimilarOutput:
    generation_id: str
    output_text: str
    skill_type: str
    eval_score: float | None
    similarity: float          # 0.0 – 1.0 cosine similarity


@dataclass
class PatternRule:
    pattern_id: str
    skill_type: str
    pattern_text: str          # injected verbatim into system prompt
    confidence: float


@dataclass
class ReviewerPref:
    signal_type: str           # e.g. "too_long"
    frequency: int
    avg_severity: float


@dataclass
class MemoryContext:
    similar_outputs: list[SimilarOutput] = field(default_factory=list)
    active_patterns: list[PatternRule] = field(default_factory=list)
    reviewer_prefs: list[ReviewerPref] = field(default_factory=list)

    def build_injection_text(self) -> str:
        """Format memory context into a text block injected into the system prompt."""
        parts: list[str] = []

        if self.active_patterns:
            rules = "\n".join(f"- {p.pattern_text}" for p in self.active_patterns)
            parts.append(f"LEARNED RULES (apply these):\n{rules}")

        if self.reviewer_prefs:
            top = sorted(self.reviewer_prefs, key=lambda r: r.frequency, reverse=True)[:3]
            prefs = "\n".join(
                f"- Avoid '{p.signal_type}' (reported {p.frequency}x, severity {p.avg_severity:.1f})"
                for p in top
            )
            parts.append(f"REVIEWER PREFERENCES:\n{prefs}")

        if self.similar_outputs:
            examples = "\n\n".join(
                f"[Past approved output, score={o.eval_score}, similarity={o.similarity:.2f}]\n"
                f"{o.output_text[:500]}..."
                for o in self.similar_outputs[:2]
            )
            parts.append(f"SIMILAR PAST OUTPUTS (for reference, do not copy):\n{examples}")

        return "\n\n".join(parts)


EMPTY_CONTEXT = MemoryContext()

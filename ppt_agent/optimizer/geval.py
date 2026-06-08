"""
G-Eval quality metric for reading material using DSPy.

Used both as a standalone scorer (called on approve to auto-set eval_score)
and as the metric function passed to the GEPA optimizer.
"""
from __future__ import annotations

import dspy

from ppt_agent.config.settings import settings


def _configure_dspy() -> None:
    lm = dspy.LM(
        model=f"openai/{settings.generation_model}",
        api_key=settings.anthropic_api_key,
        api_base=settings.llm_base_url,
        cache=False,
    )
    dspy.configure(lm=lm)


class _ReadingMaterialQuality(dspy.Signature):
    """
    Evaluate the quality of an English verbal ability reading material document
    for IT placement test preparation.

    Score criteria (each 0-1):
    1. format_compliance  — uses correct markdown structure (## headings, <details>, **Answer:**)
    2. content_depth      — explanations are thorough, examples are complete
    3. workplace_context  — all examples use product team / software workplace scenarios
    4. clarity            — beginner-friendly language, no jargon, second-person voice
    5. completeness       — all 5 sections present with minimum content requirements

    Return the average of the five criteria as `score` (0.0-1.0).
    """
    reading_material: str = dspy.InputField(desc="The generated reading material to evaluate")
    skill_type: str = dspy.InputField(desc="Skill type: concept_explainer, deck_reading, etc.")
    score: float = dspy.OutputField(desc="Average quality score 0.0–1.0")
    reasoning: str = dspy.OutputField(desc="Brief explanation of the score")


class GEvalScorer(dspy.Module):
    def __init__(self) -> None:
        self.judge = dspy.ChainOfThought(_ReadingMaterialQuality)

    def forward(self, reading_material: str, skill_type: str = "deck_reading") -> dspy.Prediction:
        _configure_dspy()
        return self.judge(reading_material=reading_material, skill_type=skill_type)


def score_reading_material(reading_material: str, skill_type: str = "deck_reading") -> tuple[float, str]:
    """
    Returns (score 0-1, reasoning).
    Safe to call from an async context via asyncio.to_thread if needed.
    """
    _configure_dspy()
    scorer = GEvalScorer()
    try:
        pred = scorer(reading_material=reading_material[:8000], skill_type=skill_type)
        raw = pred.score
        score = float(raw) if isinstance(raw, (int, float)) else 0.5
        score = max(0.0, min(1.0, score))
        return score, pred.reasoning or ""
    except Exception as exc:
        return 0.5, f"GEval scoring error: {exc}"

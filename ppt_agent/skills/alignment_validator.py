"""
Alignment validator — checks each source passage against the deck topic.

Uses claude-haiku-4-5 (cheap, ~200 tokens per call) so the developer gets
instant per-passage feedback as they add content, not only at generation time.

Verdict logic:
  pass  — score >= 0.7   all passages valid, generation unblocked
  warn  — score 0.5-0.69 marginal relevance, developer can override
  fail  — score < 0.5    generation hard-blocked, passage must be removed
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from openai import AsyncOpenAI

from ppt_agent.config.settings import settings

logger = logging.getLogger(__name__)

HAIKU_MODEL = "anthropic/claude-haiku-4-5"

ALIGNMENT_JUDGE_PROMPT = """
You are evaluating whether a book passage is relevant to a topic.

TOPIC: {topic_text}

PASSAGE (from {source_title}, page {page_ref}):
{passage_text}

Score how well this passage aligns with the topic on a scale of 0.0 to 1.0.

  0.8-1.0 — passage directly teaches this topic
  0.7     — passage is tangentially related from the right domain
  0.5-0.6 — passage is from the wrong subtopic but same broad domain
  < 0.5   — passage has no useful overlap with this topic

Respond ONLY as JSON — no preamble, no markdown:
{{"alignment_score": <float>, "verdict": "<pass|warn|fail>", "reason": "<one sentence explaining the score>"}}

Use verdict "pass" if score >= 0.7, "warn" if >= 0.5, "fail" if < 0.5.
""".strip()


@dataclass
class PassageAlignmentResult:
    passage_id: str
    source_title: str
    alignment_score: float
    verdict: Literal["pass", "warn", "fail"]
    reason: str


@dataclass
class AlignmentValidatorOutput:
    topic_id: str
    topic_text: str
    total_passage_count: int
    matched_passage_count: int
    alignment_score: float          # mean of all passage scores
    verdict: Literal["pass", "warn", "fail"]
    threshold: float = 0.7
    passage_results: list[PassageAlignmentResult] = field(default_factory=list)


async def validate_passages(
    topic_id: str,
    topic_text: str,
    passages: list[dict],           # each: {id, passage_text, source_title, page_ref}
    threshold: float = 0.7,
) -> AlignmentValidatorOutput:
    """
    Score each passage against the topic using claude-haiku-4-5.
    One LLM call per passage (~200 tokens in, ~10 tokens out).
    """
    client = AsyncOpenAI(
        api_key=settings.anthropic_api_key,
        base_url=settings.llm_base_url,
    )

    results: list[PassageAlignmentResult] = []

    for p in passages:
        prompt = ALIGNMENT_JUDGE_PROMPT.format(
            topic_text=topic_text,
            source_title=p.get("source_title") or "Unknown",
            page_ref=p.get("page_ref") or "—",
            passage_text=p["passage_text"],
        )
        try:
            resp = await client.chat.completions.create(
                model=HAIKU_MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            score = float(data.get("alignment_score", 0.0))
            verdict = _score_to_verdict(score, threshold)
            reason = data.get("reason", "")
        except Exception as exc:
            logger.warning("Alignment check failed for passage %s: %s", p["id"], exc)
            score, verdict, reason = 0.0, "fail", f"Validation error: {exc}"

        results.append(PassageAlignmentResult(
            passage_id=str(p["id"]),
            source_title=p.get("source_title") or "Unknown",
            alignment_score=score,
            verdict=verdict,
            reason=reason,
        ))

    matched = sum(1 for r in results if r.verdict == "pass")
    mean_score = sum(r.alignment_score for r in results) / len(results) if results else 1.0
    overall_verdict = _score_to_verdict(mean_score, threshold)

    return AlignmentValidatorOutput(
        topic_id=topic_id,
        topic_text=topic_text,
        total_passage_count=len(passages),
        matched_passage_count=matched,
        alignment_score=round(mean_score, 3),
        verdict=overall_verdict,
        threshold=threshold,
        passage_results=results,
    )


def _score_to_verdict(score: float, threshold: float) -> Literal["pass", "warn", "fail"]:
    if score >= threshold:
        return "pass"
    if score >= 0.5:
        return "warn"
    return "fail"

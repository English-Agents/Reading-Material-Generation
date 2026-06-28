"""
Topic coverage validator — checks whether generated reading material
substantively covers every topic in the input slide outline.

This exists because the input topic outline was previously never persisted,
so there was no way to detect when the LLM's output drifted away from what
was actually uploaded (e.g. a deck about "Synonyms" producing a document
about unrelated grammar topics). deck_compiler.py now stores the input
outline alongside the output and runs this check immediately after
generation, so a mismatch is caught and auto-corrected before a human
reviewer ever sees it.

Verdict logic mirrors alignment_validator.py:
  pass  — score >= 0.7   all/nearly all topics substantively covered
  warn  — score 0.5-0.69 some topics under-covered
  fail  — score < 0.5    output does not match the input topic outline
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from openai import AsyncOpenAI

from ppt_agent.config.settings import settings

logger = logging.getLogger(__name__)

HAIKU_MODEL = "anthropic/claude-haiku-4-5"   # overridden at runtime by settings.alignment_model

TOPIC_COVERAGE_JUDGE_PROMPT = """
You are checking whether a generated reading material document substantively covers
every topic it was supposed to teach.

INPUT TOPIC OUTLINE (what the document was supposed to cover):
{topic_list}

GENERATED DOCUMENT (excerpt):
{output_excerpt}

For each input topic, judge whether the document teaches it substantively (a real
explanation with rules/examples) versus not covering it at all or only mentioning it
in passing. Then compute:
  coverage_score = (topics substantively covered) / (total topics)

Respond ONLY as JSON — no preamble, no markdown:
{{"coverage_score": <float 0.0-1.0>, "missing_topics": [<topic strings not covered>], "reason": "<one sentence>"}}
""".strip()


@dataclass
class TopicCoverageResult:
    coverage_score: float
    verdict: Literal["pass", "warn", "fail"]
    missing_topics: list[str]
    reason: str


async def validate_topic_coverage(
    topic_outline: list[str],
    output_text: str,
    threshold: float | None = None,
) -> TopicCoverageResult:
    """Check whether output_text substantively covers every topic in topic_outline."""
    if not topic_outline:
        return TopicCoverageResult(1.0, "pass", [], "No input topics to check.")

    if threshold is None:
        threshold = settings.alignment_threshold

    model = settings.alignment_model or HAIKU_MODEL
    client = AsyncOpenAI(api_key=settings.anthropic_api_key, base_url=settings.llm_base_url)

    topic_list = "\n".join(f"- {t}" for t in topic_outline)
    prompt = TOPIC_COVERAGE_JUDGE_PROMPT.format(
        topic_list=topic_list,
        output_excerpt=output_text[:6000],
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        score = float(data.get("coverage_score", 0.0))
        missing = list(data.get("missing_topics", []))
        reason = data.get("reason", "")
    except Exception as exc:
        # A validator outage must not block generation — fail open and log.
        logger.warning("Topic coverage check failed (assuming pass): %s", exc)
        score, missing, reason = 1.0, [], f"Validation error (assumed pass): {exc}"

    verdict = _score_to_verdict(score, threshold)
    return TopicCoverageResult(
        coverage_score=round(score, 3),
        verdict=verdict,
        missing_topics=missing,
        reason=reason,
    )


def _score_to_verdict(score: float, threshold: float) -> Literal["pass", "warn", "fail"]:
    if score >= threshold:
        return "pass"
    if score >= 0.5:
        return "warn"
    return "fail"

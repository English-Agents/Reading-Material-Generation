"""
PromptFoo Python subprocess provider for reading-material quality evaluation.

PromptFoo invokes this file as:
    python caption_judge.py

It writes a JSON payload to stdin and expects a JSON result on stdout.

Stdin schema (PromptFoo default):
{
  "prompt": "<the rendered prompt string>",
  "vars": { "skill": "concept_explainer", ... },
  "output": "<the LLM output to evaluate>"
}

Stdout schema expected by PromptFoo:
{
  "pass": true | false,
  "score": 0.0 – 1.0,
  "reason": "one-line explanation"
}

This judge:
1. Checks structural Tier-1 assertions deterministically (no LLM needed)
2. Calls Claude (sync) for a Tier-2 quality rubric score
3. Combines both into a single pass/fail + score
"""
from __future__ import annotations

import json
import os
import re
import sys

from openai import OpenAI

# ── Tier 1: structural checks per skill ───────────────────────────────────────

_TIER1: dict[str, list[str]] = {
    # Format is topic-driven so section names vary — only check structural invariants
    "deck_reading": [
        "## ",          # at least one H2 section
        "| --- |",      # at least one markdown table
        "**",           # bold used for key terms
        "Exception",    # exception/restriction section present (any casing)
    ],
    "concept_explainer": [
        "## ",
        "| --- |",
        "**",
        "Exception",
    ],
    "code_walkthrough": [
        "## ",
        "```",
        "**",
    ],
    "diagram_describer": [
        "## ",
        "**",
    ],
    "figure_caption": [
        "## ",
        "**",
    ],
    "quiz_generator": [
        "**Q1.**",
        "A)",
        "B)",
        "C)",
        "D)",
        "**Answer:**",
        "**Explanation:**",
    ],
}

_MIN_LENGTH: dict[str, int] = {
    "deck_reading": 1200,
    "concept_explainer": 1200,
    "code_walkthrough": 800,
    "diagram_describer": 800,
    "figure_caption": 200,
    "quiz_generator": 400,
}

_REFUSALS = ["I cannot generate", "I'm sorry, I cannot", "I don't have enough information"]


def _tier1_check(skill: str, output: str) -> tuple[bool, list[str]]:
    failures: list[str] = []

    for marker in _TIER1.get(skill, []):
        if marker not in output:
            failures.append(f"missing '{marker}'")

    min_len = _MIN_LENGTH.get(skill, 200)
    if len(output) < min_len:
        failures.append(f"output too short ({len(output)} < {min_len})")

    for refusal in _REFUSALS:
        if refusal in output:
            failures.append(f"contains refusal phrase: '{refusal}'")

    return len(failures) == 0, failures


# ── Tier 2: LLM rubric ────────────────────────────────────────────────────────

_RUBRIC_PROMPT: dict[str, str] = {
    "deck_reading": """
You are evaluating a reading material for English grammar or verbal ability placement test prep.
Audience: beginner-to-intermediate IT placement test candidates.

The format is TOPIC-DRIVEN — section names vary by topic. What matters is quality, not specific section names.
Expected invariants: markdown tables, bold key terms, plain example sentences (no MCQ), exception/restriction cases section.

Evaluate on a scale of 1–5:
1. Clarity — Is every concept explained clearly for a complete beginner?
2. Tables — Are tables used for comparisons, type classifications, tense/pattern charts, and usage contexts?
3. Coverage — Definition, core rules, usage contexts, variations, exception cases all covered?
4. Examples — Plain example sentences, accurate, shown in General/Academic/Professional contexts where relevant?
5. Tone — Simple, second-person, conversational but professional, no filler?

Return ONLY this JSON (no other text):
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "concept_explainer": """
You are evaluating a reading material for English grammar or verbal ability placement test prep.
Format: topic-driven (section names vary). Invariants: tables, bold terms, plain examples, exception section.

Evaluate on a scale of 1–5:
1. Clarity — Concept explained clearly to a beginner?
2. Tables — Tables used for comparisons, patterns, or usage contexts?
3. Examples — Plain sentences (no MCQ), accurate and varied?
4. Coverage — Definition, rules, exceptions covered?
5. Tone — Conversational, second-person?

Return ONLY this JSON:
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "code_walkthrough": """
You are evaluating a code walkthrough reading material.

Evaluate on a scale of 1–5:
1. Code explanation — Fenced code blocks, step-by-step explanation?
2. Format — Question-style H2 headers, sub-concepts, tables?
3. Examples — Wrong → correct code with explanation?
4. Clarity — Can a beginner follow it?
5. Exceptions — Common mistakes section present?

Return ONLY this JSON:
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "diagram_describer": """
You are evaluating a diagram description reading material.

Evaluate on a scale of 1–5:
1. Accuracy — Does the description accurately capture the diagram elements and relationships?
2. Teaching — Does it teach the concept the diagram represents?
3. Examples — Do examples ask readers to interpret diagrams in workplace contexts?
4. Format — Does it follow the section structure?
5. Clarity — Is it clear for a beginner?

Return ONLY this JSON:
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "figure_caption": """
You are evaluating a figure caption for a non-technical image.

Evaluate on a scale of 1–5:
1. Accuracy — Does the caption describe what is actually shown?
2. Conciseness — Is it appropriately concise (not overly long or short)?
3. Relevance — Does it connect the image to the topic context?
4. Format — Does it follow the section structure?
5. Clarity — Is it clear for a beginner?

Return ONLY this JSON:
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "quiz_generator": """
You are evaluating a quiz generated for reading material.

Evaluate on a scale of 1–5:
1. Question count — Does it have at least 5 questions?
2. Options — Does each question have exactly 4 options (A, B, C, D)?
3. Answers — Is the correct answer clearly marked?
4. Explanations — Does each question explain why the answer is correct?
5. Variety — Are the questions varied in type (not all identical format)?

Return ONLY this JSON:
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
}


def _tier2_rubric(skill: str, output: str) -> tuple[float, str]:
    """Call the LLM synchronously for rubric scoring. Returns (avg_score_0_to_1, reason)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return 0.5, "ANTHROPIC_API_KEY not set — skipping Tier 2"

    base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("GENERATION_MODEL", "anthropic/claude-sonnet-4-6")

    client = OpenAI(api_key=api_key, base_url=base_url)
    system = _RUBRIC_PROMPT.get(skill, _RUBRIC_PROMPT["concept_explainer"])

    response = client.chat.completions.create(
        model=model,
        max_tokens=256,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"OUTPUT TO EVALUATE:\n\n{output[:6000]}"},
        ],
    )

    text = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(text)
        avg = float(data["avg"])
        reason = str(data.get("reason", ""))
        return avg / 5.0, reason
    except Exception:
        # Try to extract a number from free-form response
        m = re.search(r'"avg"\s*:\s*([\d.]+)', text)
        if m:
            return float(m.group(1)) / 5.0, text[:120]
        return 0.5, f"Could not parse rubric response: {text[:120]}"


# ── Main ──────────────────────────────────────────────────────────────────────

def evaluate(payload: dict) -> dict:
    output: str = payload.get("output", "")
    vars_: dict = payload.get("vars", {})
    skill: str = vars_.get("skill", "concept_explainer")

    # Tier 1
    tier1_ok, tier1_failures = _tier1_check(skill, output)

    # Tier 2
    tier2_score, tier2_reason = _tier2_rubric(skill, output)

    # Combined: must pass Tier 1 AND Tier 2 >= 0.7
    passed = tier1_ok and tier2_score >= 0.7

    # Final score: if Tier 1 fails hard, cap at 0.4
    if not tier1_ok:
        final_score = min(tier2_score, 0.4)
        reason = f"Tier1 failures: {'; '.join(tier1_failures[:3])}. Rubric: {tier2_reason}"
    else:
        final_score = tier2_score
        reason = tier2_reason or "Tier1 passed"

    return {
        "pass": passed,
        "score": round(final_score, 4),
        "reason": reason,
        "metadata": {
            "tier1_pass": tier1_ok,
            "tier1_failures": tier1_failures,
            "tier2_score": round(tier2_score, 4),
            "skill": skill,
        },
    }


if __name__ == "__main__":
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"pass": False, "score": 0.0, "reason": f"Invalid JSON input: {e}"}))
        sys.exit(0)

    result = evaluate(payload)
    sys.stdout.write(json.dumps(result))

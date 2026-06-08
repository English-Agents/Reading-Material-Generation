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
    "concept_explainer": [
        "<IndexList>",
        "<Section",
        "<SubSection>",
        "<MultiLineNote>",
        "<details>",
        "<HighlightedText>",
        "Answer:",
        "Explanation:",
    ],
    "code_walkthrough": [
        "<IndexList>",
        "<Section",
        "```",
        "Answer:",
        "Explanation:",
    ],
    "diagram_describer": [
        "<Section",
        "Answer:",
        "Explanation:",
    ],
    "figure_caption": [
        "<Section",
    ],
    "quiz_generator": [
        "A)",
        "B)",
        "C)",
        "D)",
        "Answer:",
        "Explanation:",
    ],
}

_MIN_LENGTH: dict[str, int] = {
    "concept_explainer": 1500,
    "code_walkthrough": 500,
    "diagram_describer": 500,
    "figure_caption": 100,
    "quiz_generator": 300,
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
    "concept_explainer": """
You are evaluating a reading material document generated for English verbal ability placement test prep.
The audience is beginner-to-intermediate learners preparing for IT company placement tests.

Evaluate the OUTPUT below on a scale of 1–5 for each criterion:
1. Clarity — Is the topic explained clearly to a beginner? (1=very unclear, 5=very clear)
2. Format — Does it have IndexList, 5 Sections, SubSections with 3 collapsible examples each, MultiLineNote? (1=missing most, 5=complete)
3. Examples — Do all examples use product team / software workplace scenarios? (1=none, 5=all)
4. Explanations — Does each example explain why the correct answer is right AND why each wrong option is wrong? (1=missing, 5=thorough)
5. Tone — Is it professional yet approachable, free of jargon, no filler phrases? (1=poor, 5=excellent)

Return ONLY this JSON (no other text):
{"scores": [s1, s2, s3, s4, s5], "avg": <average>, "reason": "<one sentence>"}
""",
    "code_walkthrough": """
You are evaluating a code walkthrough reading material.

Evaluate on a scale of 1–5:
1. Code explanation — Are code blocks properly fenced and explained line by line? (1=poor, 5=excellent)
2. Format — Does it follow the required section structure? (1=missing, 5=complete)
3. Examples — Do examples show correct vs incorrect code usage with workplace context? (1=none, 5=thorough)
4. Clarity — Can a beginner follow the explanation? (1=no, 5=yes)
5. Explanations — Are wrong answer explanations clear? (1=missing, 5=thorough)

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

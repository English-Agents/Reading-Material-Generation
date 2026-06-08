"""
Phase 4 eval pipeline tests — all mocked, no network or DB.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppt_agent.evals.caption_judge import _tier1_check, evaluate
from ppt_agent.evals.run_regression import (
    TIER1_MIN_PASS_RATE,
    TIER2_MIN_AVG,
    check_promotion_gate,
    parse_results,
)


# ── caption_judge: Tier 1 ─────────────────────────────────────────────────────

GOOD_CONCEPT_OUTPUT = (
    "<IndexList>\n"
    "<Section id='overview'>\n"
    "<SubSection>\n"
    "<MultiLineNote>\n"
    "<details>\n"
    "<HighlightedText>Example 1</HighlightedText>\n"
    "Answer: B) The correct option\n"
    "Explanation: Because X is true and the other options are wrong for these reasons.\n"
    "</SubSection>\n"
    "</Section>\n"
) * 10  # repeat to exceed 1500 chars


def test_tier1_passes_on_well_formed_concept_output():
    ok, failures = _tier1_check("concept_explainer", GOOD_CONCEPT_OUTPUT)
    assert ok, failures


def test_tier1_fails_on_missing_index_list():
    output = GOOD_CONCEPT_OUTPUT.replace("<IndexList>", "")
    ok, failures = _tier1_check("concept_explainer", output)
    assert not ok
    assert any("IndexList" in f for f in failures)


def test_tier1_fails_on_too_short_output():
    ok, failures = _tier1_check("concept_explainer", "Short")
    assert not ok
    assert any("too short" in f for f in failures)


def test_tier1_fails_on_refusal():
    ok, failures = _tier1_check("concept_explainer", GOOD_CONCEPT_OUTPUT + " I cannot generate this.")
    assert not ok
    assert any("refusal" in f for f in failures)


def test_tier1_code_walkthrough_requires_code_fence():
    base = (
        "<IndexList>\n<Section\nAnswer: A)\nExplanation: test\n"
    ) * 5  # length OK
    ok, failures = _tier1_check("code_walkthrough", base)
    assert not ok
    assert any("```" in f for f in failures)


def test_tier1_quiz_requires_abcd_options():
    output = "Answer: A)\nExplanation: test\n" * 5
    ok, failures = _tier1_check("quiz_generator", output)
    # missing B) C) D)
    assert not ok


# ── caption_judge: evaluate() with mocked Tier 2 ─────────────────────────────

def test_evaluate_passes_good_output():
    with patch("ppt_agent.evals.caption_judge._tier2_rubric", return_value=(0.85, "good quality")):
        result = evaluate({
            "output": GOOD_CONCEPT_OUTPUT,
            "vars": {"skill": "concept_explainer"},
        })
    assert result["pass"] is True
    assert result["score"] == 0.85
    assert result["metadata"]["tier1_pass"] is True


def test_evaluate_fails_on_tier1_failure():
    short_output = "Missing everything."
    with patch("ppt_agent.evals.caption_judge._tier2_rubric", return_value=(0.8, "rubric ok")):
        result = evaluate({
            "output": short_output,
            "vars": {"skill": "concept_explainer"},
        })
    assert result["pass"] is False
    assert result["score"] <= 0.4   # capped when Tier 1 fails
    assert result["metadata"]["tier1_pass"] is False


def test_evaluate_fails_on_low_tier2():
    with patch("ppt_agent.evals.caption_judge._tier2_rubric", return_value=(0.5, "below threshold")):
        result = evaluate({
            "output": GOOD_CONCEPT_OUTPUT,
            "vars": {"skill": "concept_explainer"},
        })
    assert result["pass"] is False


def test_evaluate_with_unknown_skill_uses_defaults():
    with patch("ppt_agent.evals.caption_judge._tier2_rubric", return_value=(0.9, "ok")):
        result = evaluate({
            "output": "x" * 300,
            "vars": {"skill": "nonexistent_skill"},
        })
    # min_length for unknown defaults to 200 — 300 chars passes
    assert result["metadata"]["skill"] == "nonexistent_skill"


# ── run_regression: parse_results ────────────────────────────────────────────

def _make_results_json(skill: str, tier1_pass: bool, tier2_score: float) -> dict:
    """Build a minimal PromptFoo results.json structure."""
    return {
        "results": {
            "results": [
                {
                    "vars": {"skill": skill},
                    "gradingResult": {
                        "componentResults": [
                            {
                                "type": "contains",
                                "metric": "format-check",
                                "pass": tier1_pass,
                                "reason": "" if tier1_pass else "missing marker",
                            },
                            {
                                "type": "llm-rubric",
                                "metric": "rubric-quality",
                                "pass": tier2_score >= 0.7,
                                "score": tier2_score,
                                "reason": "rubric result",
                            },
                        ]
                    },
                }
            ]
        }
    }


def test_parse_results_passing():
    raw = _make_results_json("concept_explainer", tier1_pass=True, tier2_score=0.8)
    summaries = parse_results(raw)
    assert "concept_explainer" in summaries
    s = summaries["concept_explainer"]
    assert s["tier1_pass_rate"] == 1.0
    assert s["tier2_avg_score"] == 0.8


def test_parse_results_tier1_failure():
    raw = _make_results_json("concept_explainer", tier1_pass=False, tier2_score=0.8)
    summaries = parse_results(raw)
    s = summaries["concept_explainer"]
    assert s["tier1_pass_rate"] == 0.0
    assert len(s["failures"]) == 1


def test_parse_results_skill_filter():
    raw = _make_results_json("code_walkthrough", tier1_pass=True, tier2_score=0.9)
    summaries = parse_results(raw, skill_filter="concept_explainer")
    assert summaries == {}


# ── run_regression: promotion gate ───────────────────────────────────────────

def test_gate_passes_all_green():
    summaries = {
        "concept_explainer": {"tier1_pass_rate": 1.0, "tier2_avg_score": 0.82, "failures": []},
        "quiz_generator":    {"tier1_pass_rate": 1.0, "tier2_avg_score": 0.75, "failures": []},
    }
    passed, msgs = check_promotion_gate(summaries)
    assert passed
    assert msgs == []


def test_gate_blocks_on_tier1_failure():
    summaries = {
        "concept_explainer": {"tier1_pass_rate": 0.8, "tier2_avg_score": 0.85, "failures": []},
    }
    passed, msgs = check_promotion_gate(summaries)
    assert not passed
    assert any("Tier1" in m for m in msgs)


def test_gate_blocks_on_tier2_too_low():
    summaries = {
        "concept_explainer": {"tier1_pass_rate": 1.0, "tier2_avg_score": 0.65, "failures": []},
    }
    passed, msgs = check_promotion_gate(summaries)
    assert not passed
    assert any("Tier2" in m for m in msgs)


def test_gate_blocks_when_both_fail():
    summaries = {
        "concept_explainer": {"tier1_pass_rate": 0.5, "tier2_avg_score": 0.4, "failures": []},
    }
    passed, msgs = check_promotion_gate(summaries)
    assert not passed
    assert len(msgs) == 2


# ── test_case_generator: YAML builder ────────────────────────────────────────

def test_yaml_block_contains_skill_and_assertions():
    from ppt_agent.evals.test_case_generator import _build_yaml_block

    block = _build_yaml_block(
        description="auto: concept_explainer — too_short",
        skill="concept_explainer",
        slide_title="Verbal Ability",
        slide_body="Test body",
        assertions=[
            {"type": "javascript", "value": "output.length > 800", "metric": "min-length"},
        ],
    )
    assert "concept_explainer" in block
    assert "min-length" in block
    assert "output.length > 800" in block
    assert "Verbal Ability" in block


def test_yaml_block_handles_special_chars():
    from ppt_agent.evals.test_case_generator import _build_yaml_block

    block = _build_yaml_block(
        description='auto: test — with "quotes"',
        skill="quiz_generator",
        slide_title='Title with "quotes" and\nnewlines',
        slide_body="body",
        assertions=[],
    )
    # Should not raise and should produce parseable-looking YAML
    assert "quiz_generator" in block


@pytest.mark.asyncio
async def test_generate_test_case_appends_to_yaml(tmp_path):
    from ppt_agent.evals import test_case_generator

    # Override the output path
    fake_yaml = tmp_path / "auto_generated.yaml"
    fake_yaml.write_text("# Auto-generated\n")

    import uuid as uuid_mod

    gen_id = str(uuid_mod.uuid4())

    mock_gen = MagicMock()
    mock_gen.id = uuid_mod.UUID(gen_id)
    mock_gen.skill_type = "concept_explainer"
    mock_gen.output_text = "short rejected output"

    mock_feedback = MagicMock()
    mock_feedback.signal_type = "too_short"
    mock_feedback.reviewer_note = "Too brief, missing examples"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_gen)

    mock_scalars = MagicMock()
    mock_scalars.scalars.return_value.all.return_value = [mock_feedback]
    mock_db.execute = AsyncMock(return_value=mock_scalars)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("ppt_agent.evals.test_case_generator.get_db_session", return_value=mock_session),
        patch("ppt_agent.evals.test_case_generator._AUTO_YAML", fake_yaml),
        patch(
            "ppt_agent.evals.test_case_generator._generate_rubric_prompt",
            new=AsyncMock(return_value="Score 1-5 on quality. Return SCORE: N/5."),
        ),
    ):
        await test_case_generator.generate_test_case(gen_id)

    content = fake_yaml.read_text()
    assert "concept_explainer" in content
    assert "too_short" in content

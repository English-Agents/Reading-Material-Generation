"""
Run the PromptFoo regression suite and write results back to the DB.

Usage:
    python -m ppt_agent.evals.run_regression
    python -m ppt_agent.evals.run_regression --skill concept_explainer
    python -m ppt_agent.evals.run_regression --prompt-version-id <uuid>

Exit codes:
    0 — all checks passed
    1 — Tier 1 pass rate < 1.0 OR avg Tier 2 < 0.7
    2 — subprocess / JSON error
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_EVALS_DIR = Path(__file__).parent
_CONFIG = _EVALS_DIR / "promptfoo.yaml"
_RESULTS_FILE = _EVALS_DIR / "results.json"

# Thresholds — must match the plan
TIER1_MIN_PASS_RATE = 1.0   # all structural checks must pass
TIER2_MIN_AVG = 0.7         # rubric score threshold (0–1 scale)


# ── PromptFoo runner ──────────────────────────────────────────────────────────

def run_promptfoo(extra_args: list[str] | None = None) -> dict:
    """
    Invoke `npx promptfoo eval` and return the parsed results JSON.
    Raises RuntimeError on non-zero exit or missing output file.
    """
    cmd = [
        "npx", "promptfoo", "eval",
        "--config", str(_CONFIG),
        "--output", str(_RESULTS_FILE),
        "--no-cache",
    ] + (extra_args or [])

    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        raise RuntimeError(
            f"promptfoo exited {proc.returncode}:\n{proc.stderr[-2000:]}"
        )

    if not _RESULTS_FILE.exists():
        raise RuntimeError(f"promptfoo did not produce {_RESULTS_FILE}")

    with _RESULTS_FILE.open() as f:
        return json.load(f)


# ── Result parsing ────────────────────────────────────────────────────────────

def _is_tier1(assert_result: dict) -> bool:
    metric = assert_result.get("metric", "")
    type_ = assert_result.get("type", "")
    return type_ not in ("llm-rubric",) and metric != "rubric-quality"


def parse_results(raw: dict, skill_filter: str | None = None) -> dict[str, dict]:
    """
    Parse PromptFoo results.json into per-skill summary dicts.

    Returns:
        {
          "concept_explainer": {
            "tier1_pass_rate": 1.0,
            "tier2_avg_score": 0.82,
            "total_tests": 3,
            "passed": 3,
            "failures": []
          },
          ...
        }
    """
    results_per_skill: dict[str, dict] = {}

    # PromptFoo results.json structure varies by version; handle both shapes
    tests = (
        raw.get("results", {}).get("results", [])   # v0.82+
        or raw.get("results", [])
    )

    for test in tests:
        vars_ = test.get("vars", {})
        skill = vars_.get("skill", "unknown")

        if skill_filter and skill != skill_filter:
            continue

        if skill not in results_per_skill:
            results_per_skill[skill] = {
                "tier1_total": 0,
                "tier1_passed": 0,
                "tier2_scores": [],
                "failures": [],
            }

        bucket = results_per_skill[skill]
        asserts = test.get("gradingResult", {}).get("componentResults", [])

        for a in asserts:
            if _is_tier1(a):
                bucket["tier1_total"] += 1
                if a.get("pass"):
                    bucket["tier1_passed"] += 1
                else:
                    bucket["failures"].append({
                        "type": a.get("type"),
                        "metric": a.get("metric"),
                        "reason": a.get("reason", ""),
                    })
            else:
                score = a.get("score", 0.0)
                bucket["tier2_scores"].append(float(score))

    # Summarise
    summaries: dict[str, dict] = {}
    for skill, b in results_per_skill.items():
        t1_total = b["tier1_total"] or 1
        tier2_avg = sum(b["tier2_scores"]) / len(b["tier2_scores"]) if b["tier2_scores"] else 0.0
        summaries[skill] = {
            "tier1_pass_rate": b["tier1_passed"] / t1_total,
            "tier2_avg_score": round(tier2_avg, 4),
            "tier1_passed": b["tier1_passed"],
            "tier1_total": b["tier1_total"],
            "failures": b["failures"],
        }

    return summaries


# ── DB write-back ─────────────────────────────────────────────────────────────

async def write_to_db(
    summaries: dict[str, dict],
    prompt_version_id: str | None = None,
) -> None:
    """Write pass_rate and avg_rubric_score back to prompt_versions."""
    from ppt_agent.db.models import PromptVersion
    from ppt_agent.db.session import get_db_session
    from ppt_agent.memory.prompt_store import get_active

    async with get_db_session() as db:
        for skill, summary in summaries.items():
            if prompt_version_id:
                version = await db.get(PromptVersion, uuid.UUID(prompt_version_id))
            else:
                version = await get_active(skill, db)

            if version is None:
                logger.warning("No active prompt version for %s — skipping DB write", skill)
                continue

            version.pass_rate = summary["tier1_pass_rate"]
            version.avg_rubric_score = summary["tier2_avg_score"]
            logger.info(
                "Updated %s (id=%s): pass_rate=%.3f rubric=%.3f",
                skill, version.id,
                summary["tier1_pass_rate"],
                summary["tier2_avg_score"],
            )


# ── Gate logic ────────────────────────────────────────────────────────────────

def check_promotion_gate(summaries: dict[str, dict]) -> tuple[bool, list[str]]:
    """
    Returns (all_passed, list_of_failure_messages).
    Blocks promotion if any skill fails Tier 1 or Tier 2 threshold.
    """
    failures: list[str] = []
    for skill, s in summaries.items():
        if s["tier1_pass_rate"] < TIER1_MIN_PASS_RATE:
            failures.append(
                f"{skill}: Tier1 pass rate {s['tier1_pass_rate']:.0%} < 100%"
            )
        if s["tier2_avg_score"] < TIER2_MIN_AVG:
            failures.append(
                f"{skill}: Tier2 avg {s['tier2_avg_score']:.3f} < {TIER2_MIN_AVG}"
            )
    return len(failures) == 0, failures


# ── CLI entry point ───────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        raw = run_promptfoo()
    except RuntimeError as exc:
        logger.error("PromptFoo run failed: %s", exc)
        return 2

    summaries = parse_results(raw, skill_filter=args.skill)

    if not summaries:
        logger.warning("No results found (skill filter: %s)", args.skill)
        return 2

    print("\n── Eval Results ──────────────────────────────")
    for skill, s in summaries.items():
        status = "✓" if s["tier1_pass_rate"] >= TIER1_MIN_PASS_RATE and s["tier2_avg_score"] >= TIER2_MIN_AVG else "✗"
        print(
            f" {status} {skill:25s}  "
            f"Tier1={s['tier1_passed']}/{s['tier1_total']}  "
            f"Tier2={s['tier2_avg_score']:.3f}"
        )
        for f in s["failures"]:
            print(f"     FAIL [{f['type']}] {f['reason'][:80]}")
    print()

    if not args.dry_run:
        await write_to_db(summaries, prompt_version_id=args.prompt_version_id)

    all_passed, gate_failures = check_promotion_gate(summaries)
    if not all_passed:
        print("── Promotion BLOCKED ──────────────────────────")
        for msg in gate_failures:
            print(f"  ✗ {msg}")
        return 1

    print("── All gates passed — promotion allowed ───────")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PromptFoo regression suite")
    parser.add_argument("--skill", default=None, help="Filter to a single skill_type")
    parser.add_argument("--prompt-version-id", default=None, help="UUID of prompt version to update")
    parser.add_argument("--dry-run", action="store_true", help="Skip DB write-back")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))

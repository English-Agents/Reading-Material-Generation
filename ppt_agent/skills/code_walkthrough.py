from __future__ import annotations

import sys
from pathlib import Path

from ppt_agent import llm
from ppt_agent.memory.types import MemoryContext
from ppt_agent.skills.circuit_breaker import RepairRequired, with_circuit_breaker
from ppt_agent.skills.cost_tracker import record as record_cost

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from slide_parser import ParsedSlide


async def run(
    slide: ParsedSlide,
    prompt_text: str,
    format_schema: dict,
    memory_context: MemoryContext,
    *,
    generation_id: str,
    db,
) -> str | RepairRequired:
    memory_injection = memory_context.build_injection_text()
    system = prompt_text
    if memory_injection:
        system = f"{system}\n\n{memory_injection}"

    user_content = (
        f"SLIDE TITLE: {slide.title or '(untitled)'}\n\n"
        f"SLIDE BODY (may contain code snippets):\n{slide.body_text}\n\n"
        f"SPEAKER NOTES:\n{slide.speaker_notes or '(none)'}"
    )

    output, tokens_in, tokens_out, _ = await llm.complete(system=system, user=user_content, max_tokens=4096)
    await record_cost(generation_id, tokens_in, tokens_out, db)
    return output


run = with_circuit_breaker("code_walkthrough")(run)

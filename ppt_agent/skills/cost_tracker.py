"""
Records token usage and USD cost to the generations table after every skill call.

Pricing for claude-sonnet-4-6 (confirmed 2025-06):
  Input:  $3.00 per million tokens
  Output: $15.00 per million tokens
"""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

# Pricing constants — update if Anthropic changes rates
_INPUT_USD_PER_TOKEN = 3.00 / 1_000_000
_OUTPUT_USD_PER_TOKEN = 15.00 / 1_000_000


def _cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in * _INPUT_USD_PER_TOKEN + tokens_out * _OUTPUT_USD_PER_TOKEN, 6)


async def record(
    generation_id: str,
    tokens_in: int,
    tokens_out: int,
    db,  # AsyncSession — typed loosely to avoid circular import
) -> float:
    """
    Write token counts and computed USD cost to generations table.
    Returns cost_usd for logging.
    """
    cost_usd = tokens_in * _INPUT_USD_PER_TOKEN + tokens_out * _OUTPUT_USD_PER_TOKEN

    from ppt_agent.db.models import Generation

    gen = await db.get(Generation, uuid.UUID(generation_id))
    if gen is not None:
        gen.tokens_in = tokens_in
        gen.tokens_out = tokens_out
        gen.token_cost_usd = round(cost_usd, 6)

    logger.debug(
        "generation=%s tokens_in=%d tokens_out=%d cost=$%.6f",
        generation_id, tokens_in, tokens_out, cost_usd,
    )
    return cost_usd

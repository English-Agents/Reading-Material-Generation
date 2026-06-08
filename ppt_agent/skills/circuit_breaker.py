"""
Circuit breaker decorator for all skill run() functions.

Usage (at module level in each skill file):
    run = with_circuit_breaker("concept_explainer")(run)

On any exception during skill execution:
- Increments generation.retry_count in DB
- If retry_count >= MAX_RETRIES: sets status='needs_repair',
  inserts into repair_queue, returns RepairRequired (not an exception)
- Below MAX_RETRIES: re-raises the exception
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from ppt_agent.config.settings import settings
from ppt_agent.db.models import Generation, RepairQueue
from ppt_agent.db.session import get_db_session

logger = logging.getLogger(__name__)


@dataclass
class RepairRequired:
    generation_id: str
    skill_type: str
    reason: str


def with_circuit_breaker(skill_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            generation_id: str | None = kwargs.get("generation_id")

            try:
                return await fn(*args, **kwargs)

            except Exception as exc:
                logger.warning(
                    "Skill %s failed for generation %s: %s",
                    skill_type, generation_id, exc,
                )

                if generation_id is None:
                    raise

                async with get_db_session() as db:
                    gen = await db.get(Generation, uuid.UUID(generation_id))
                    if gen is None:
                        raise

                    gen.retry_count = (gen.retry_count or 0) + 1

                    if gen.retry_count >= settings.max_retries:
                        gen.status = "needs_repair"
                        db.add(
                            RepairQueue(
                                generation_id=gen.id,
                                retry_count=gen.retry_count,
                                last_error=str(exc)[:2000],
                            )
                        )
                        logger.error(
                            "Generation %s moved to repair queue after %d retries",
                            generation_id, gen.retry_count,
                        )
                        return RepairRequired(
                            generation_id=generation_id,
                            skill_type=skill_type,
                            reason=str(exc),
                        )

                raise

        return wrapper
    return decorator

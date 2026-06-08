"""
Update all active prompt versions in the DB with the latest seed prompts.
Run after changing format_schema.py or seed_prompts.py:

    python reseed_prompts.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def reseed() -> None:
    from ppt_agent.db.models import PromptVersion
    from ppt_agent.db.session import get_db_session
    from ppt_agent.skills.seed_prompts import SEED_PROMPTS

    async with get_db_session() as db:
        for skill_type, prompt_text in SEED_PROMPTS.items():
            existing = (
                await db.execute(
                    select(PromptVersion).where(
                        PromptVersion.skill_type == skill_type,
                        PromptVersion.status == "active",
                    )
                )
            ).scalar_one_or_none()

            if existing:
                existing.prompt_text = prompt_text
                logger.info("Updated active prompt for %s (%s)", skill_type, existing.id)
            else:
                version = PromptVersion(
                    skill_type=skill_type,
                    prompt_text=prompt_text,
                    status="active",
                )
                db.add(version)
                logger.info("Inserted new active prompt for %s", skill_type)

    logger.info("Reseed complete.")


if __name__ == "__main__":
    asyncio.run(reseed())

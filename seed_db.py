"""
One-time script: insert initial 'active' prompt versions for all 5 skills.
Run after `alembic upgrade head`:
    python seed_db.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def seed() -> None:
    from ppt_agent.db.models import PromptVersion
    from ppt_agent.db.session import get_db_session
    from ppt_agent.skills.seed_prompts import SEED_PROMPTS

    async with get_db_session() as db:
        for skill_type, prompt_text in SEED_PROMPTS.items():
            # Skip if an active version already exists (idempotent)
            existing = (
                await db.execute(
                    select(PromptVersion).where(
                        PromptVersion.skill_type == skill_type,
                        PromptVersion.status == "active",
                    )
                )
            ).scalar_one_or_none()

            if existing:
                logger.info("Skipping %s — active version already exists (%s)", skill_type, existing.id)
                continue

            version = PromptVersion(
                skill_type=skill_type,
                prompt_text=prompt_text,
                status="active",
            )
            db.add(version)
            logger.info("Inserted active prompt for %s", skill_type)

    logger.info("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())

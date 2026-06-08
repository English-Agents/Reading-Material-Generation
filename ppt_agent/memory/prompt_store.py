from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ppt_agent.db.models import PromptVersion

logger = logging.getLogger(__name__)


async def get_active(skill_type: str, db) -> PromptVersion | None:
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.skill_type == skill_type, PromptVersion.status == "active")
        .order_by(PromptVersion.promoted_at.desc().nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_shadow(skill_type: str, db) -> PromptVersion | None:
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.skill_type == skill_type, PromptVersion.status == "shadow")
        .order_by(PromptVersion.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def promote(version_id, db) -> None:
    """Atomically promote version_id to active, retire all other active versions for its skill."""
    version = await db.get(PromptVersion, version_id)
    if version is None:
        raise ValueError(f"PromptVersion {version_id} not found")

    skill_type = version.skill_type
    now = datetime.now(timezone.utc)

    # Retire current active
    actives = (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.skill_type == skill_type,
                PromptVersion.status == "active",
            )
        )
    ).scalars().all()
    for v in actives:
        v.status = "retired"
        v.retired_at = now

    version.status = "active"
    version.promoted_at = now
    logger.info("Promoted prompt version %s for %s", version_id, skill_type)


async def retire(version_id, db) -> None:
    version = await db.get(PromptVersion, version_id)
    if version is None:
        return
    version.status = "retired"
    version.retired_at = datetime.now(timezone.utc)


async def rollback(skill_type: str, db) -> bool:
    """Promote parent of current active version. Returns True if rollback succeeded."""
    active = await get_active(skill_type, db)
    if active is None or active.parent_id is None:
        logger.warning("Cannot rollback %s — no parent version", skill_type)
        return False

    await promote(active.parent_id, db)
    logger.warning("Rolled back %s to parent version %s", skill_type, active.parent_id)
    return True

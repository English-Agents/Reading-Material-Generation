"""
Ops API + background monitoring job.

Background job (every 15 min):
  1. Run shadow A/B promotion checks
  2. Check for score drops, repair queue depth/age
  3. Auto-rollback if unresolved score_drop alert exists

Routes:
  GET /ops/dashboard   — per-skill stats snapshot
  GET /ops/alerts      — unresolved alerts list
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ppt_agent.api.deps import get_db
from ppt_agent.config.settings import settings
from ppt_agent.db.models import Alert, Generation, RepairQueue
from ppt_agent.memory.prompt_store import get_active

router = APIRouter()
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]

# ── Alert thresholds ──────────────────────────────────────────────────────────
_SCORE_DROP_WINDOW = 100        # compare last 100 vs previous 100 generations
_SCORE_DROP_THRESHOLD = 0.3     # avg drop of 0.3 triggers alert
_QUEUE_DEPTH_THRESHOLD = 50     # pending repairs
_QUEUE_AGE_HOURS = 24           # oldest unresolved repair


# ── Response schemas ──────────────────────────────────────────────────────────

class SkillStats(BaseModel):
    skill_type: str
    total_generations: int
    approved: int
    rejected: int
    needs_repair: int
    avg_eval_score: float | None
    avg_cost_usd: float | None
    active_prompt_version: str | None


class DashboardResponse(BaseModel):
    as_of: str
    skills: list[SkillStats]
    open_alerts: int
    repair_queue_depth: int


class AlertItem(BaseModel):
    id: str
    alert_type: str
    skill_type: str | None
    message: str
    created_at: str


# ── Background job ────────────────────────────────────────────────────────────

async def ops_background_job() -> None:
    """Infinite loop — runs every 15 minutes inside the FastAPI lifespan."""
    while True:
        try:
            await _run_ops_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("ops_background_job error: %s", exc, exc_info=True)
        await asyncio.sleep(900)  # 15 minutes


async def _run_ops_cycle() -> None:
    from ppt_agent.db.session import get_db_session

    async with get_db_session() as db:
        # 1. Shadow promotion
        try:
            from ppt_agent.skills.shadow import evaluate_shadow_promotions
            await evaluate_shadow_promotions(db)
        except Exception as exc:
            logger.warning("Shadow promotion check failed: %s", exc)

        # 2. Alert checks
        await _check_score_drops(db)
        await _check_queue_depth(db)
        await _check_queue_age(db)

        # 3. Auto-rollback if unresolved score_drop alert
        await _maybe_auto_rollback(db)


async def _check_score_drops(db: AsyncSession) -> None:
    from ppt_agent.memory.generation_store import get_recent_eval_scores
    from ppt_agent.memory.prompt_store import get_active

    skill_types = ["concept_explainer", "code_walkthrough", "diagram_describer",
                   "figure_caption", "quiz_generator"]

    for skill in skill_types:
        scores = await get_recent_eval_scores(skill, db, window=_SCORE_DROP_WINDOW * 2)
        if len(scores) < _SCORE_DROP_WINDOW * 2:
            continue

        recent_avg = sum(scores[:_SCORE_DROP_WINDOW]) / _SCORE_DROP_WINDOW
        previous_avg = sum(scores[_SCORE_DROP_WINDOW:]) / _SCORE_DROP_WINDOW
        drop = previous_avg - recent_avg

        if drop >= _SCORE_DROP_THRESHOLD:
            await _upsert_alert(
                db,
                alert_type="score_drop",
                skill_type=skill,
                message=(
                    f"{skill}: avg score dropped {drop:.3f} "
                    f"(prev={previous_avg:.3f} → recent={recent_avg:.3f})"
                ),
            )


async def _check_queue_depth(db: AsyncSession) -> None:
    depth = (
        await db.execute(
            select(func.count(RepairQueue.id)).where(RepairQueue.status == "pending")
        )
    ).scalar() or 0

    if depth >= _QUEUE_DEPTH_THRESHOLD:
        await _upsert_alert(
            db,
            alert_type="repair_queue_depth",
            skill_type=None,
            message=f"Repair queue depth {depth} >= threshold {_QUEUE_DEPTH_THRESHOLD}",
        )


async def _check_queue_age(db: AsyncSession) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_QUEUE_AGE_HOURS)
    oldest = (
        await db.execute(
            select(RepairQueue.created_at)
            .where(RepairQueue.status == "pending", RepairQueue.created_at <= cutoff)
            .order_by(RepairQueue.created_at.asc())
            .limit(1)
        )
    ).scalar()

    if oldest:
        age_h = (datetime.now(timezone.utc) - oldest.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        await _upsert_alert(
            db,
            alert_type="repair_queue_age",
            skill_type=None,
            message=f"Oldest pending repair is {age_h:.1f}h old (threshold={_QUEUE_AGE_HOURS}h)",
        )


async def _upsert_alert(
    db: AsyncSession,
    alert_type: str,
    skill_type: str | None,
    message: str,
) -> None:
    """Insert an alert only if no unresolved alert of the same type+skill exists."""
    existing = (
        await db.execute(
            select(Alert).where(
                Alert.alert_type == alert_type,
                Alert.skill_type == skill_type,
                Alert.resolved == False,
            )
        )
    ).scalar_one_or_none()

    if existing:
        return  # already open

    db.add(Alert(alert_type=alert_type, skill_type=skill_type, message=message))
    logger.warning("Alert raised: [%s] %s — %s", alert_type, skill_type or "global", message)


async def _maybe_auto_rollback(db: AsyncSession) -> None:
    """If there's an unresolved score_drop alert, roll back that skill's prompt."""
    from ppt_agent.memory.prompt_store import rollback

    open_drops = (
        await db.execute(
            select(Alert).where(
                Alert.alert_type == "score_drop",
                Alert.resolved == False,
            )
        )
    ).scalars().all()

    for alert in open_drops:
        if alert.skill_type:
            did_rollback = await rollback(alert.skill_type, db)
            if did_rollback:
                alert.resolved = True
                logger.warning("Auto-rollback executed for %s", alert.skill_type)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: DB):
    skill_types = ["concept_explainer", "code_walkthrough", "diagram_describer",
                   "figure_caption", "quiz_generator"]

    skills_stats: list[SkillStats] = []
    for skill in skill_types:
        rows = (
            await db.execute(
                select(
                    Generation.status,
                    func.count(Generation.id).label("cnt"),
                    func.avg(Generation.eval_score).label("avg_score"),
                    func.avg(Generation.token_cost_usd).label("avg_cost"),
                )
                .where(Generation.skill_type == skill, Generation.is_shadow == False)
                .group_by(Generation.status)
            )
        ).all()

        counts: dict[str, int] = {}
        avg_score = avg_cost = None
        for row in rows:
            counts[row.status] = int(row.cnt)
            if row.avg_score is not None:
                avg_score = float(row.avg_score)
            if row.avg_cost is not None:
                avg_cost = float(row.avg_cost)

        active_pv = await get_active(skill, db)

        skills_stats.append(SkillStats(
            skill_type=skill,
            total_generations=sum(counts.values()),
            approved=counts.get("approved", 0),
            rejected=counts.get("rejected", 0),
            needs_repair=counts.get("needs_repair", 0),
            avg_eval_score=avg_score,
            avg_cost_usd=avg_cost,
            active_prompt_version=str(active_pv.id) if active_pv else None,
        ))

    open_alerts = (
        await db.execute(
            select(func.count(Alert.id)).where(Alert.resolved == False)
        )
    ).scalar() or 0

    queue_depth = (
        await db.execute(
            select(func.count(RepairQueue.id)).where(RepairQueue.status == "pending")
        )
    ).scalar() or 0

    return DashboardResponse(
        as_of=datetime.now(timezone.utc).isoformat(),
        skills=skills_stats,
        open_alerts=int(open_alerts),
        repair_queue_depth=int(queue_depth),
    )


@router.get("/alerts", response_model=list[AlertItem])
async def get_alerts(db: DB, resolved: bool = False):
    rows = (
        await db.execute(
            select(Alert)
            .where(Alert.resolved == resolved)
            .order_by(Alert.created_at.desc())
            .limit(100)
        )
    ).scalars().all()

    return [
        AlertItem(
            id=str(a.id),
            alert_type=a.alert_type,
            skill_type=a.skill_type,
            message=a.message,
            created_at=a.created_at.isoformat(),
        )
        for a in rows
    ]


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, db: DB):
    from fastapi import HTTPException
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved = True
    return {"status": "resolved"}

"""
Image pipeline: Redis vision cache + two LLM vision calls per image.

Call 1 — is_technical_diagram: YES/NO
Call 2 — full structured description JSON

Cache key: img:{md5}:vision   TTL: 7 days
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_VISION_TTL = 604800  # 7 days
_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis
        from ppt_agent.config.settings import settings
        _redis_client = aioredis.from_url(
            settings.redis_url,
            max_connections=settings.redis_image_pool_max_connections,
            decode_responses=True,
        )
    return _redis_client


@dataclass
class DiagramDescription:
    type: str
    key_elements: list[str]
    data_points: list[str]
    relationships: list[str]
    is_technical: bool


@dataclass
class VisionResult:
    md5: str
    is_technical_diagram: bool
    description: DiagramDescription
    from_cache: bool


async def process_image(
    md5: str,
    base64_data: str,
    mime_type: str,
) -> VisionResult:
    redis = await _get_redis()
    cache_key = f"img:{md5}:vision"

    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        desc = DiagramDescription(**data["description"])
        return VisionResult(
            md5=md5,
            is_technical_diagram=data["is_technical_diagram"],
            description=desc,
            from_cache=True,
        )

    result = await _run_vision_pipeline(md5, base64_data, mime_type)

    payload = {
        "is_technical_diagram": result.is_technical_diagram,
        "description": {
            "type": result.description.type,
            "key_elements": result.description.key_elements,
            "data_points": result.description.data_points,
            "relationships": result.description.relationships,
            "is_technical": result.description.is_technical,
        },
    }
    await redis.set(cache_key, json.dumps(payload), ex=_VISION_TTL)
    logger.debug("Cached vision result for %s", md5)
    return result


async def _run_vision_pipeline(
    md5: str,
    base64_data: str,
    mime_type: str,
) -> VisionResult:
    from ppt_agent import llm

    image = {"base64_data": base64_data, "mime_type": mime_type}

    # Call 1: technical diagram check — just need YES/NO
    call1_text, _, _ = await llm.complete_with_images(
        system="You classify images for a document processing pipeline.",
        user_text=(
            "Is this image a technical diagram, flowchart, architecture diagram, "
            "UML diagram, sequence diagram, or data chart? Answer YES or NO only."
        ),
        images=[image],
        max_tokens=10,
    )
    is_technical = call1_text.strip().upper().startswith("YES")

    # Call 2: structured description
    desc_prompt = (
        "Describe this image. Return a JSON object with exactly these fields:\n"
        '{"type":"brief label","key_elements":["..."],'
        '"data_points":["..."],"relationships":["..."]}\n'
        "Return only the JSON object, no markdown wrapper."
    )
    call2_text, _, _ = await llm.complete_with_images(
        system="You describe images for a document processing pipeline. Return only valid JSON.",
        user_text=desc_prompt,
        images=[image],
        max_tokens=512,
    )

    raw = call2_text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Vision description JSON parse failed for %s, using fallback", md5)
        parsed = {"type": "unknown", "key_elements": [], "data_points": [], "relationships": []}

    description = DiagramDescription(
        type=parsed.get("type", "unknown"),
        key_elements=parsed.get("key_elements", []),
        data_points=parsed.get("data_points", []),
        relationships=parsed.get("relationships", []),
        is_technical=is_technical,
    )
    return VisionResult(
        md5=md5,
        is_technical_diagram=is_technical,
        description=description,
        from_cache=False,
    )


async def is_technical_diagram_cached(md5: str) -> Optional[bool]:
    """Return cached flag without an API call. Returns None if not yet cached."""
    redis = await _get_redis()
    cached = await redis.get(f"img:{md5}:vision")
    if cached:
        return json.loads(cached).get("is_technical_diagram")
    return None

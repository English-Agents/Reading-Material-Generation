"""Unit tests for image/pipeline.py — uses fakeredis and mocked llm.complete_with_images."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def fake_redis():
    import fakeredis.aioredis as fakeredis
    return fakeredis.FakeRedis(decode_responses=True)


async def test_technical_diagram_detected(fake_redis):
    call1_result = ("YES", 10, 1)
    call2_result = (json.dumps({
        "type": "flowchart",
        "key_elements": ["start", "process", "decision", "end"],
        "data_points": [],
        "relationships": ["start -> process", "process -> decision", "decision -> end"],
    }), 50, 80)

    import ppt_agent.image.pipeline as pipeline_mod
    pipeline_mod._redis_client = fake_redis

    with patch("ppt_agent.llm.complete_with_images", new=AsyncMock(side_effect=[call1_result, call2_result])):
        from ppt_agent.image.pipeline import process_image
        result = await process_image("abc123", "fakebase64==", "image/png")

    assert result.is_technical_diagram is True
    assert result.description.type == "flowchart"
    assert "start" in result.description.key_elements
    assert result.from_cache is False


async def test_non_technical_diagram(fake_redis):
    call1_result = ("NO", 10, 1)
    call2_result = (json.dumps({
        "type": "photograph",
        "key_elements": ["people", "whiteboard", "office"],
        "data_points": [],
        "relationships": [],
    }), 50, 60)

    import ppt_agent.image.pipeline as pipeline_mod
    pipeline_mod._redis_client = fake_redis

    with patch("ppt_agent.llm.complete_with_images", new=AsyncMock(side_effect=[call1_result, call2_result])):
        from ppt_agent.image.pipeline import process_image
        result = await process_image("def456", "fakebase64==", "image/jpeg")

    assert result.is_technical_diagram is False
    assert result.description.type == "photograph"


async def test_cache_hit_skips_api(fake_redis):
    await fake_redis.set(
        "img:cached123:vision",
        json.dumps({
            "is_technical_diagram": True,
            "description": {
                "type": "bar_chart",
                "key_elements": ["x-axis", "y-axis", "bars"],
                "data_points": ["Q1: 50", "Q2: 75"],
                "relationships": [],
                "is_technical": True,
            },
        }),
        ex=604800,
    )

    import ppt_agent.image.pipeline as pipeline_mod
    pipeline_mod._redis_client = fake_redis

    mock_llm = AsyncMock()
    with patch("ppt_agent.llm.complete_with_images", new=mock_llm):
        from ppt_agent.image.pipeline import process_image
        result = await process_image("cached123", "fakebase64==", "image/png")

    assert result.from_cache is True
    assert result.description.type == "bar_chart"
    mock_llm.assert_not_called()


async def test_is_technical_diagram_cached_returns_none_for_unknown(fake_redis):
    import ppt_agent.image.pipeline as pipeline_mod
    pipeline_mod._redis_client = fake_redis

    from ppt_agent.image.pipeline import is_technical_diagram_cached
    result = await is_technical_diagram_cached("unknown_md5")
    assert result is None


async def test_is_technical_diagram_cached_returns_flag(fake_redis):
    await fake_redis.set(
        "img:known_md5:vision",
        json.dumps({
            "is_technical_diagram": False,
            "description": {
                "type": "photo", "key_elements": [], "data_points": [],
                "relationships": [], "is_technical": False,
            },
        }),
        ex=604800,
    )

    import ppt_agent.image.pipeline as pipeline_mod
    pipeline_mod._redis_client = fake_redis

    from ppt_agent.image.pipeline import is_technical_diagram_cached
    result = await is_technical_diagram_cached("known_md5")
    assert result is False

"""
Thin LLM wrapper — uses OpenAI SDK pointed at OpenRouter.

All skills call complete() or complete_with_images() instead of instantiating
the Anthropic SDK directly. Swapping provider = change settings only.
"""
from __future__ import annotations

from openai import AsyncOpenAI, OpenAI

from ppt_agent.config.settings import settings


def _async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.anthropic_api_key,
        base_url=settings.llm_base_url,
    )


def _sync_client() -> OpenAI:
    return OpenAI(
        api_key=settings.anthropic_api_key,
        base_url=settings.llm_base_url,
    )


async def complete(
    system: str,
    user: str,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """
    Returns (output_text, tokens_in, tokens_out).
    """
    client = _async_client()
    resp = await client.chat.completions.create(
        model=settings.generation_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)


async def complete_with_images(
    system: str,
    user_text: str,
    images: list[dict],        # list of {base64_data, mime_type}
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """
    Multi-modal call. Images are inlined as base64 data URLs.
    Returns (output_text, tokens_in, tokens_out).
    """
    client = _async_client()

    content: list[dict] = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['mime_type']};base64,{img['base64_data']}"
            },
        })
    content.append({"type": "text", "text": user_text})

    resp = await client.chat.completions.create(
        model=settings.generation_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)


def complete_sync(
    system: str,
    user: str,
    max_tokens: int = 256,
) -> tuple[str, int, int]:
    """
    Synchronous version — used by caption_judge.py (PromptFoo subprocess).
    """
    client = _sync_client()
    resp = client.chat.completions.create(
        model=settings.generation_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)

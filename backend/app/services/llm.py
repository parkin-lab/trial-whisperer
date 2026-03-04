"""
OpenClaw gateway LLM client.
Uses the OpenAI-compatible /v1/chat/completions endpoint exposed by the local OpenClaw gateway.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> str | None:
    """
    Call OpenClaw's OpenAI-compatible chat completions endpoint.
    Returns the assistant message text, or None on failure.
    """
    settings = get_settings()

    if not settings.openclaw_gateway_token:
        logger.warning("OPENCLAW_GATEWAY_TOKEN not set - LLM features disabled")
        return None

    resolved_model = model or settings.llm_model

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    headers = {
        "Authorization": f"Bearer {settings.openclaw_gateway_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{settings.openclaw_gateway_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        logger.exception("OpenClaw gateway HTTP error: %s %s", exc.response.status_code, exc.response.text[:200])
        return None
    except Exception as exc:
        logger.exception("OpenClaw gateway call failed: %s", exc)
        return None

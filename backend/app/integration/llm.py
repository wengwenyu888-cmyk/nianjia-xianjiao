"""LLM 适配骨架（智能体建议只出建议，不落账）。

二期实现：组装入参 → 调用 → 解析 → 写建议留痕。当前只给最小可运行封装。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def chat(prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
    """调用 LLM 返回文本内容。

    Raises:
        RuntimeError: 未配置 LLM_API_KEY 时给出明确提示，避免线上静默失败。
    """
    if not settings.LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY，智能体能力暂不可用")
    messages: list[dict[str, str]] = (
        [{"role": "system", "content": system}] if system else []
    ) + [{"role": "user", "content": prompt}]
    async with httpx.AsyncClient(base_url=settings.LLM_BASE_URL, timeout=30.0) as client:
        resp = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            json={"model": settings.LLM_MODEL, "messages": messages, **kwargs},
        )
        resp.raise_for_status()
        payload = resp.json()
    return str(payload["choices"][0]["message"]["content"])

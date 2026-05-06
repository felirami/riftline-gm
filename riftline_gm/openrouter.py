from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from riftline_gm.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0


@dataclass(frozen=True)
class ImageResult:
    image_url: str
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0


class OpenRouterClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.openrouter_base_url,
            timeout=httpx.Timeout(90.0, connect=15.0),
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
                "X-Title": config.app_title,
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 900,
        temperature: float = 0.8,
    ) -> ChatResult:
        selected = model or self.config.openrouter_text_model
        payload: dict[str, Any] = {
            "model": selected,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await self._post_chat(payload, fallback_model=self.config.openrouter_fallback_model)
        message = data["choices"][0]["message"]
        return ChatResult(
            text=_content_to_text(message.get("content", "")).strip(),
            model=data.get("model", selected),
            **_usage(data),
        )

    async def draft_image_prompt(
        self,
        *,
        language_instruction: str,
        profile_instruction: str,
        original_prompt: str,
        model: str | None = None,
    ) -> ChatResult:
        messages = [
            {
                "role": "system",
                "content": (
                    "Rewrite user image requests into one concise image-generation prompt for a tabletop RPG GM. "
                    "Keep it vivid, visual, safe for provider policy, and do not add copyrighted character likenesses. "
                    "Write only the final image prompt. Follow the requested campaign language; do not default to English "
                    "unless the language instruction asks for it."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Campaign language/style: {language_instruction}\n"
                    "The final image prompt itself must follow that language/style.\n"
                    f"Game profile visual direction: {profile_instruction}\n"
                    f"User request: {original_prompt}"
                ),
            },
        ]
        try:
            return await self.chat(messages, model=model, max_tokens=180, temperature=0.5)
        except Exception:
            logger.exception("Failed to draft image prompt; using local fallback")
            fallback = (
                f"{profile_instruction}, tabletop RPG scene art, dramatic lighting: {original_prompt}"
            )
            return ChatResult(text=fallback, model="local-fallback")

    async def image(self, prompt: str, *, model: str | None = None, aspect_ratio: str = "16:9") -> ImageResult:
        selected = model or self.config.openrouter_image_model
        payload: dict[str, Any] = {
            "model": selected,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect_ratio, "image_size": "1K"},
            "stream": False,
        }
        data = await self._post_chat(payload, fallback_model=None)
        message = data["choices"][0]["message"]
        image_url = _first_image_url(message)
        if not image_url:
            raise RuntimeError("OpenRouter returned no image URL")
        return ImageResult(
            image_url=image_url,
            text=_content_to_text(message.get("content", "")).strip(),
            model=data.get("model", selected),
            **_usage(data),
        )

    async def _post_chat(self, payload: dict[str, Any], *, fallback_model: str | None) -> dict[str, Any]:
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception:
            if not fallback_model or payload.get("model") == fallback_model:
                raise
            logger.exception("OpenRouter request failed for %s; trying fallback %s", payload.get("model"), fallback_model)
            fallback_payload = dict(payload)
            fallback_payload["model"] = fallback_model
            response = await self._client.post("/chat/completions", json=fallback_payload)
            response.raise_for_status()
            return response.json()


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "text" in item:
                    parts.append(str(item["text"]))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _first_image_url(message: dict[str, Any]) -> str | None:
    for image in message.get("images") or []:
        image_url = image.get("image_url") or image.get("imageUrl") or {}
        url = image_url.get("url")
        if url:
            return str(url)
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"image_url", "output_image"}:
                image_url = item.get("image_url") or item.get("imageUrl") or {}
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                if url:
                    return str(url)
    return None


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_cost": float(usage.get("cost") or usage.get("total_cost") or 0.0),
    }

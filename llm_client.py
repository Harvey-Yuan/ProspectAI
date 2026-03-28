"""
LLM Client — InsForge REST API
================================
Wraps InsForge's /api/ai/chat/completion endpoint with a simple interface
that mirrors the openai SDK response shape used in the rest of the codebase.

Usage:
    from llm_client import chat, MODEL

    response = chat(messages=[{"role": "user", "content": "Hello"}])
    print(response.content)          # str
    print(response.model)            # str
    print(response.usage)            # dict
"""

import os
from dataclasses import dataclass
from typing import Any
import httpx
from dotenv import load_dotenv

load_dotenv()

MODEL = "anthropic/claude-sonnet-4.5"

_BASE_URL = os.getenv("INSFORGE_BASE_URL", "https://uw7kmade.us-east.insforge.app")
_ANON_KEY = os.getenv("INSFORGE_ANON_KEY", "")

# Strip trailing /ai/v1 if someone puts the full path in the env var
_BASE_URL = _BASE_URL.rstrip("/")
if _BASE_URL.endswith("/ai/v1"):
    _BASE_URL = _BASE_URL[: -len("/ai/v1")]

_CHAT_ENDPOINT = f"{_BASE_URL}/api/ai/chat/completion"


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: dict[str, Any]
    tool_calls: list[dict] | None = None


def chat(
    messages: list[dict],
    model: str = MODEL,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    tools: list[dict] | None = None,
) -> ChatResponse:
    """
    Call InsForge chat completion endpoint.
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    if not _ANON_KEY:
        raise ValueError("INSFORGE_ANON_KEY is not set — check your .env file")

    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        payload["maxTokens"] = max_tokens
    if system_prompt:
        payload["systemPrompt"] = system_prompt
    if tools:
        payload["tools"] = tools

    headers = {
        "Authorization": f"Bearer {_ANON_KEY}",
        "Content-Type": "application/json",
    }

    r = httpx.post(_CHAT_ENDPOINT, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()

    return ChatResponse(
        content=data.get("text", ""),
        model=data.get("metadata", {}).get("model", model),
        usage=data.get("metadata", {}).get("usage", {}),
        tool_calls=data.get("tool_calls"),
    )

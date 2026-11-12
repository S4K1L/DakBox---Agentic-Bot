"""Chat with any provider that speaks the OpenAI chat-completions format (ChatGPT, Gemini's compatible endpoint, DeepSeek, Groq, OpenRouter,
a local Ollama, ...). No SDK: one small HTTP call, so a provider's quirks stay visible here. Written from the providers' public documentation;
never run against a real provider in this build (tests use a stand-in)."""
from __future__ import annotations

import httpx

from .. import aikey


class LlmHttpError(Exception):
    """The provider answered with an error. Carries the status code only, so nothing sensitive can end up in a log."""

    def __init__(self, status_code: int):
        super().__init__(f"provider error {status_code}")
        self.status_code = status_code


async def chat(messages: list[dict], *, system: str, tools: list[dict] | None = None, max_tokens: int = 1500, small: bool = False) -> dict:
    """One completion. Returns the provider's assistant message ({"content": ..., "tool_calls": [...]})."""
    pid = aikey.active()
    key = aikey.get_key(pid)
    mdl = aikey.small_model(pid) if small else aikey.model(pid)
    base = aikey.base_url(pid)
    if not (key and mdl and base):
        raise LlmHttpError(0)
    if pid == "custom":
        await aikey.validate_base(base)           # the address is checked again on every call, not only when it was saved
    body: dict = {"model": mdl, "messages": [{"role": "system", "content": system}] + messages}
    body["max_completion_tokens" if pid == "openai" else "max_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    async with aikey.client(45.0) as c:
        r = await c.post(f"{base}/chat/completions", json=body, headers=aikey.auth_headers(pid, key))
    if r.status_code != 200:
        raise LlmHttpError(r.status_code)
    try:
        return (r.json()["choices"][0]["message"]) or {}
    except (ValueError, KeyError, IndexError, TypeError):
        raise LlmHttpError(502) from None


def text_of(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, list):                        # some providers return a list of parts
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""

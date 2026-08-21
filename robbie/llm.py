"""Minimal OpenAI-compatible chat client with streaming (DeepSeek, OpenAI, etc.).

One job: send messages, yield reply text as it streams. No retries for
token-level hiccups mid-stream; callers decide how to handle errors.
"""

import json
from collections.abc import Iterator

import httpx

from .config import Config


class LLMError(RuntimeError):
    """Raised when the LLM API call fails."""


class LLMClient:
    def __init__(self, config: Config, timeout: float = 120.0) -> None:
        self._config = config
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        """Send messages and return the complete reply (non-streaming)."""
        body = {
            "model": self._config.model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            response = self._client.post(
                f"{self._config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"API request failed: {exc}") from exc

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected API response shape: {data!r}") from exc

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        """Send messages and yield reply text chunks as they stream."""
        body = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
        }
        try:
            with self._client.stream(
                "POST",
                f"{self._config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, ValueError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise LLMError(f"API request failed: {exc}") from exc

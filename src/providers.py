"""Bounded text generation over documented model APIs.

Purpose: Discover local models and normalize provider streams.
Inputs: Validated provider, model, messages; optional process-held API keys.
Outputs: Text chunks, or sanitized ProviderError messages.
Assumptions: Single-user local application; no automatic paid retries or fallback.
Author: Carter Tan.
"""

import json
import os
from collections.abc import AsyncIterator

import httpx

PROVIDERS = {
    "ollama": {"label": "Ollama", "base": "http://127.0.0.1:11434", "key": None},
    "lmstudio": {"label": "LM Studio", "base": "http://127.0.0.1:1234", "key": None},
    "openai": {"label": "OpenAI", "base": "https://api.openai.com", "key": "OPENAI_API_KEY"},
    "anthropic": {"label": "Claude", "base": "https://api.anthropic.com", "key": "ANTHROPIC_API_KEY"},
    "openrouter": {"label": "OpenRouter", "base": "https://openrouter.ai", "key": "OPENROUTER_API_KEY"},
}


class ProviderError(Exception):
    """Safe-to-display provider failure, without remote payloads or credentials."""


def is_cloud(provider: str) -> bool:
    """Return whether a provider sends data outside this Mac."""
    return bool(PROVIDERS[provider]["key"])


async def discover(provider: str) -> dict:
    """Discover local models; check cloud credential presence without paid calls."""
    spec = PROVIDERS[provider]
    result = {"id": provider, "label": spec["label"], "cloud": is_cloud(provider), "models": []}
    if spec["key"]:
        result["status"] = "Key available · unverified" if os.environ.get(spec["key"]) else "API key needed"
        return result
    try:
        path = "/api/tags" if provider == "ollama" else "/v1/models"
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(spec["base"] + path)
            response.raise_for_status()
        data = response.json()
        entries = data["models"] if provider == "ollama" else data["data"]
        # Embedding-only models cannot answer chat requests.
        result["models"] = [m["name" if provider == "ollama" else "id"] for m in entries
                            if not any(s in m.get("name", m.get("id", "")).lower()
                                       for s in ("embed", "bge-m3", "cloud"))]
        result["status"] = "Connected" if result["models"] else "Connected · no chat models"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result["status"] = "Not running"
    return result


def request_spec(provider: str, model: str, system: str, messages: list[dict]) -> tuple:
    """Build a provider-specific request using a fixed endpoint allowlist."""
    spec = PROVIDERS[provider]
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(spec["key"], "") if spec["key"] else None
    if spec["key"] and not key:
        raise ProviderError(f"{spec['label']} needs a server-side {spec['key']}. See the setup guide.")
    if provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        path = "/v1/messages"
        body = {"model": model, "system": system, "messages": messages, "max_tokens": 2048, "stream": True}
    elif provider == "openai":
        headers["Authorization"] = f"Bearer {key}"
        path = "/v1/responses"
        body = {"model": model, "instructions": system, "input": messages,
                "max_output_tokens": 2048, "store": False, "stream": True}
    elif provider == "ollama":
        path = "/api/chat"
        body = {"model": model, "messages": [{"role": "system", "content": system}] + messages,
                "stream": True, "options": {"num_predict": 2048, "num_ctx": 8192}}
    else:
        path = "/api/v1/chat/completions" if provider == "openrouter" else "/v1/chat/completions"
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "messages": [{"role": "system", "content": system}] + messages,
                "max_tokens": 2048, "stream": True}
    return spec["base"] + path, headers, body


def parse_event(provider: str, event: dict) -> tuple[str, bool]:
    """Normalize text and successful completion; never expose hidden reasoning."""
    if event.get("error") or event.get("type") in ("error", "response.failed"):
        raise ProviderError("The provider rejected or interrupted this request. Check the model and account.")
    if provider == "ollama":
        if event.get("done") and event.get("done_reason") == "length":
            raise ProviderError("The output limit was reached; partial output has been kept.")
        return event.get("message", {}).get("content", ""), bool(event.get("done"))
    if provider == "openai":
        if event.get("type") == "response.incomplete":
            raise ProviderError("The response reached a provider limit; partial output has been kept.")
        return (event.get("delta", "") if event.get("type") == "response.output_text.delta" else "",
                event.get("type") == "response.completed")
    if provider == "anthropic":
        delta = event.get("delta", {})
        return (delta.get("text", "") if delta.get("type") == "text_delta" else "",
                event.get("type") == "message_stop")
    choices = event.get("choices", [])
    if not choices:
        return "", False
    if choices[0].get("finish_reason") == "length":
        raise ProviderError("The output limit was reached; partial output has been kept.")
    return choices[0].get("delta", {}).get("content") or "", choices[0].get("finish_reason") == "stop"


async def generate(provider: str, model: str, system: str, messages: list[dict]) -> AsyncIterator[str]:
    """Stream bounded text with explicit timeout and no automatic billing retries."""
    url, headers, body = request_spec(provider, model, system, messages)
    completed = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5), trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 300:
                    raise ProviderError(f"Provider returned HTTP {response.status_code}. Check model, access and limits.")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if provider != "ollama":
                        if not line.startswith("data: "):
                            continue
                        line = line[6:]
                    if line == "[DONE]":
                        break
                    event = json.loads(line)
                    chunk, done = parse_event(provider, event)
                    completed = completed or done
                    if chunk:
                        yield chunk
        if not completed:
            raise ProviderError("The stream ended before completion. Partial output has been kept.")
    except httpx.TimeoutException as exc:
        raise ProviderError("The model timed out. Try a smaller model or shorter request.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("Cannot reach the provider. Check that the local server is running or the network is available.") from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("The provider returned an unsupported response format.") from exc

"""Minimal OpenAI-compatible chat client (stdlib only).

Both the mock server and a real ``llama-server`` speak the OpenAI
``/v1/chat/completions`` protocol, so a thin urllib client covers the core path
with zero third-party dependencies.  The optional ``openai`` package is still
listed in requirements for users who prefer it, but the harness does not need
it to run.
"""
from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
from typing import Any, Optional


class LLMError(RuntimeError):
    pass


def chat(base_url: str, model: str, messages: list[dict], *,
         tools: Optional[list[dict]] = None,
         tool_choice: Optional[str] = None,
         thinking: bool = False,
         max_tokens: int = 2048,
         temperature: float = 0.7,
         timeout: float = 600.0,
         stream: bool = False,
         cancel_event: Optional["object"] = None) -> dict:
    """Call /v1/chat/completions and return a normalised dict:

        {
          "content": str | None,
          "reasoning": str,
          "tool_calls": list | None,
          "finish_reason": str,
          "usage": {"prompt_tokens", "completion_tokens", "total_tokens"},
          "stopped": bool,        # True if cancelled mid-flight
        }

    When ``stream=True`` the request is sent with ``"stream": true`` and the
    response is consumed incrementally as Server-Sent Events so a ``Stop`` can
    abort it by closing the connection (llama-server frees the slot on client
    disconnect).  The UI still BATCH-renders — this only changes the transport.
    ``cancel_event`` (a ``threading.Event``-like with ``is_set()``) is polled on
    every SSE line; when set, the connection is closed and ``finish_reason`` is
    ``"stopped"`` with the partial text returned so far.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": bool(stream),
        # Gemma hybrid-reasoning toggle (spec §5.5).
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer local",
                 "Accept": "text/event-stream" if stream else "application/json"},
        method="POST")

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise LLMError(f"HTTP {e.code} from {url}: {detail[:500]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"cannot reach model server at {url}: {e}") from e

    if not stream:
        try:
            body = json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()
        return _normalise_completion(body, stopped=False)

    # --- streaming transport ---------------------------------------------- #
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" not in ctype:
        # Server (or mock in non-stream mode) ignored the stream flag and
        # returned a whole JSON completion body — parse it as normal.
        try:
            body = json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()
        stopped = bool(cancel_event is not None and cancel_event.is_set())
        return _normalise_completion(body, stopped=stopped)

    return _consume_stream(resp, cancel_event)


def _normalise_completion(body: dict, *, stopped: bool) -> dict:
    """Shape a normal (non-stream) completion body into the canonical dict."""
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    usage = body.get("usage", {}) or {}
    return {
        "content": msg.get("content"),
        "reasoning": msg.get("reasoning_content") or "",
        "tool_calls": msg.get("tool_calls"),
        "finish_reason": choice.get("finish_reason", "stop"),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "stopped": stopped,
    }


def _consume_stream(resp, cancel_event) -> dict:
    """Read an SSE ``/chat/completions`` stream and reconstruct one completion.

    Accumulates ``delta.content`` and ``delta.reasoning_content``; rebuilds
    streamed ``tool_calls`` by index (id + function.name captured from the first
    delta of each index, function.arguments string deltas concatenated). Stops
    on ``data: [DONE]`` or when ``cancel_event`` is set (closing the response so
    llama-server releases the slot), reporting ``finish_reason="stopped"``.
    """
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_acc: dict[int, dict] = {}   # index -> {id, type, function:{name,arguments}}
    finish_reason = "stop"
    usage = {}
    stopped = False

    try:
        for raw in resp:
            if cancel_event is not None and cancel_event.is_set():
                stopped = True
                finish_reason = "stopped"
                break

            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":"):
                continue          # keep-alive comment / blank separator
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = chunk["usage"]
            choice = (chunk.get("choices") or [{}])[0]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])

            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                slot = tool_calls_acc.setdefault(
                    idx, {"id": None, "type": "function",
                          "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if tc.get("type"):
                    slot["type"] = tc["type"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
    finally:
        # Closing the connection signals llama-server to stop the slot.
        with contextlib.suppress(Exception):
            resp.close()

    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)

    tool_calls = None
    if tool_calls_acc:
        tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            if tc["id"] is None:
                tc["id"] = (tc["function"]["name"] or f"call_{idx}")
            tool_calls.append(tc)

    return {
        # Preserve the existing "None when empty + has tool_calls" contract.
        "content": content if (content or not tool_calls) else None,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "stopped": stopped,
    }


def approx_tokens(messages: list[dict]) -> int:
    """Rough token estimate for compaction triggers (chars / 4)."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c) // 4
        for tc in (m.get("tool_calls") or []):
            args = (tc.get("function") or {}).get("arguments") or ""
            total += len(str(args)) // 4
    return max(1, total)

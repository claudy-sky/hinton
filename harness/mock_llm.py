"""Zero-dependency mock of an OpenAI-compatible ``llama-server``.

Lets the full application boot, persist data, route models, run the agent loop
and exercise the markdown/KaTeX/code/Mermaid renderer *before* the ~12 GB of
real Gemma weights are downloaded.  It is intentionally deterministic and
keyword-driven so behaviour is predictable in development.

Implements just enough of the API surface the harness uses:
  * ``GET  /health``                 -> readiness probe
  * ``GET  /v1/models``              -> model list
  * ``POST /v1/chat/completions``    -> completion. ``"stream": false`` (default)
    returns one JSON body (spec: batch render); ``"stream": true`` emits SSE
    ``data:`` chunks so the Stop button is demoable.

Supported request extras:
  * ``stream``                       -> SSE streaming (delta chunks + [DONE])
  * ``tools`` / ``tool_choice``      -> may return a simulated tool_call
  * ``chat_template_kwargs.enable_thinking`` -> fills ``reasoning_content``
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------- #
# Canned content
# --------------------------------------------------------------------------- #
_SHOWCASE = r"""좋아요 — 렌더링 스택을 한 번에 점검할 수 있는 데모입니다.

## 1. 수식 (KaTeX)
인라인 예시: 최소 작용의 원리는 $\delta \int_{t_1}^{t_2} L\,dt = 0$ 로 표현됩니다.

블록 수식:
$$
\frac{d}{dt}\left(\frac{\partial L}{\partial \dot{q}_i}\right) - \frac{\partial L}{\partial q_i} = 0
$$

## 2. 코드 (highlight.js)
```python
def lagrangian(T, V):
    # L = T - V  (kinetic minus potential)
    return T - V
```

## 3. 표
| 형식론 | 핵심 변수 | 방정식 |
|--------|-----------|--------|
| 뉴턴   | 힘 $F$    | $F = ma$ |
| 라그랑주 | $q,\dot q$ | 오일러–라그랑주 |

## 4. 다이어그램 (Mermaid)
```mermaid
graph LR
  A[좌표 q] --> B[라그랑지안 L]
  B --> C[오일러-라그랑주]
  C --> D[운동 방정식]
```

## 5. 함수 그래프
[PLOT: sin(x)]
"""


def _mock_reply(messages: list[dict], thinking: bool) -> tuple[str, str]:
    """Return (content, reasoning)."""
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = (m.get("content") or "")
            break
    low = last_user.lower()

    if any(k in last_user for k in ("렌더", "데모", "showcase")) or "demo" in low:
        content = _SHOWCASE
    elif last_user.strip():
        content = (
            f"**(개발용 모의 모델 응답)**\n\n"
            f"요청을 확인했습니다: “{last_user.strip()[:200]}”.\n\n"
            "실제 Gemma 4 가중치가 설치되면 이 자리에서 모델이 직접 답합니다. "
            "지금은 앱·라우팅·렌더링을 검증하기 위한 모의 응답입니다.\n\n"
            "- 마크다운 렌더링 정상\n"
            "- 인라인 수식 $E = mc^2$ 정상\n"
            "- `렌더 데모` 라고 입력하면 전체 렌더링 쇼케이스를 볼 수 있어요."
        )
    else:
        content = "무엇을 도와드릴까요? (개발용 모의 모델)"

    reasoning = ""
    if thinking:
        reasoning = ("사용자의 의도를 파악하고, 모의 환경임을 알린 뒤 "
                     "렌더링 점검 방법을 안내하기로 결정.")
    return content, reasoning


def _maybe_tool_call(messages: list[dict], tools: list[dict]) -> dict | None:
    """Simulate a tool call when a trigger word appears and the matching tool exists."""
    if not tools:
        return None
    # If the most recent message is already a tool result, don't loop again.
    if messages and messages[-1].get("role") == "tool":
        return None
    names = {t.get("function", {}).get("name") for t in tools}
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m.get("content") or ""
            break

    triggers = [
        (("검색", "찾아", "최신", "뉴스"), "web_search", {"query": last_user[:120]}),
        (("그림", "이미지 그", "그려"), "generate_image", {"prompt": last_user[:120]}),
        (("논문", "학술", "arxiv"), "academic_search", {"query": last_user[:120]}),
    ]
    for words, fn, args in triggers:
        if fn in names and any(w in last_user for w in words):
            return {
                "id": "call_mock_1",
                "type": "function",
                "function": {"name": fn, "arguments": json.dumps(args, ensure_ascii=False)},
            }
    return None


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split_pieces(text: str, n: int) -> list[str]:
    """Split ``text`` into roughly ``n`` contiguous pieces (for SSE deltas)."""
    text = text or ""
    if not text:
        return [""]
    n = max(1, n)
    size = max(1, -(-len(text) // n))   # ceil division
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    server_version = "OpenLMMock/1.0"

    def log_message(self, *_args):  # silence
        pass

    def _send_json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._send_json({"status": "ok", "mock": True})
        elif self.path.startswith("/v1/models"):
            self._send_json({"object": "list", "data": [
                {"id": "gemma-4-mock", "object": "model", "owned_by": "openlm"}]})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "bad json"}, 400)
            return

        if not self.path.startswith("/v1/chat/completions"):
            self._send_json({"error": "not found"}, 404)
            return

        messages = req.get("messages", [])
        tools = req.get("tools", [])
        stream = bool(req.get("stream", False))
        thinking = bool(
            (req.get("chat_template_kwargs") or {}).get("enable_thinking", False))
        model = req.get("model", "gemma-4-mock")

        tool_call = _maybe_tool_call(messages, tools)
        if tool_call:
            content, reasoning, finish = "", "", "tool_calls"
        else:
            content, reasoning = _mock_reply(messages, thinking)
            finish = "stop"

        if stream:
            self._stream_completion(model, content, reasoning, tool_call, finish)
            return

        if tool_call:
            msg = {"role": "assistant", "content": None, "tool_calls": [tool_call]}
        else:
            msg = {"role": "assistant", "content": content}
            if reasoning:
                msg["reasoning_content"] = reasoning

        prompt_toks = sum(_approx_tokens(m.get("content") or "") for m in messages)
        completion_toks = _approx_tokens(content + reasoning)
        self._send_json({
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": prompt_toks,
                "completion_tokens": completion_toks,
                "total_tokens": prompt_toks + completion_toks,
            },
        })

    # ------------------------------------------------------------------ #
    # SSE streaming (Stop-button demo)
    # ------------------------------------------------------------------ #
    def _sse_send(self, obj) -> bool:
        """Write one ``data:`` line. Returns False if the client disconnected."""
        try:
            payload = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _stream_completion(self, model, content, reasoning, tool_call, finish):
        """Emit the canned reply as SSE chunks with small delays so a Stop is
        actually demoable, then ``data: [DONE]``."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk",
                "model": model}

        if tool_call:
            # Single chunk carrying the tool call, then DONE.
            chunk = {**base, "choices": [{"index": 0, "delta": {
                "role": "assistant", "tool_calls": [{
                    "index": 0,
                    "id": tool_call.get("id"),
                    "type": tool_call.get("type", "function"),
                    "function": tool_call.get("function", {}),
                }]}, "finish_reason": None}]}
            if self._sse_send(chunk):
                self._sse_send({**base, "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
            self._sse_send("[DONE]")
            return

        # Optional leading reasoning chunk.
        if reasoning and not self._sse_send(
                {**base, "choices": [{"index": 0,
                                      "delta": {"reasoning_content": reasoning},
                                      "finish_reason": None}]}):
            return

        # Split the content into ~8 pieces, emitted with a pause between each so
        # a Stop can land mid-stream.
        pieces = _split_pieces(content, 8)
        for i, piece in enumerate(pieces):
            if i:
                time.sleep(0.15)
            ok = self._sse_send({**base, "choices": [
                {"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
            if not ok:
                return   # client disconnected (Stop) — server drops the slot
        self._sse_send({**base, "choices": [
            {"index": 0, "delta": {}, "finish_reason": finish}]})
        self._sse_send("[DONE]")


def start_mock_server(host: str, port: int) -> ThreadingHTTPServer:
    """Start the mock server in a daemon thread and return the httpd handle."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True,
                         name=f"mock-llm:{port}")
    t.start()
    return httpd


if __name__ == "__main__":  # manual smoke test
    from . import config
    srv = start_mock_server(config.SERVER_HOST, config.E4B_PORT)
    print(f"mock llm on http://{config.SERVER_HOST}:{config.E4B_PORT}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()

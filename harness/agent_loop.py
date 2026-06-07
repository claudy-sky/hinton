"""The agentic tool-calling loop (spec §7) and context compaction (§7.2).

``run_agent`` advertises the available tools (plus the control tools
``escalate_to_12b`` / ``descalate``), calls the active model, executes any
requested tools, and loops until the model produces a final answer or the turn
cap is hit.  Escalation/descalation are intercepted here so the *next* model
call lands on the freshly-loaded server while the conversation continues
seamlessly (spec §5.1).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from . import config, llm_client
from .model_manager import manager
from .tools.registry import registry

# --------------------------------------------------------------------------- #
# Control-tool schemas (spec §5.3 / §5.4)
# --------------------------------------------------------------------------- #
ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "escalate_to_12b",
        "description": "현재 질문이 E4B로 처리하기 어려운 고난도 추론·다단계 작업일 때 12B로 전환한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "에스컬레이션 이유"},
                "thinking": {"type": "boolean", "default": False,
                             "description": "12B에서 thinking 모드를 켤지 여부"},
            },
            "required": ["reason"],
        },
    },
}

DESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "descalate",
        "description": ("이후 작업이 단순 Q&A·요약·번역·짧은 코드 수준이거나, 다단계 작업이 "
                        "완전히 끝났거나, 사용자가 E4B로 충분한 새 주제로 전환했을 때 호출한다. "
                        "그 외에는 호출하지 않는다."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

DESCALATE_SYSTEM_HINT = (
    "너는 현재 12B 모델이다. 다음 조건이면 descalate() 도구를 호출하라: "
    "(1) 이후 예상 작업이 단순 Q&A·요약·번역·짧은 코드 수준, "
    "(2) 현재 다단계 작업이 완전히 종료됨, "
    "(3) 사용자가 주제를 전환해 E4B로 충분한 새 맥락 시작. 그 외에는 호출하지 않는다."
)


def _emit(on_event: Optional[Callable[[dict], None]], **kw) -> None:
    if on_event:
        try:
            on_event(kw)
        except Exception:
            pass


def run_agent(messages: list[dict], *,
              thinking: bool = False,
              tool_names: Optional[list[str]] = None,
              allow_escalation: bool = True,
              max_turns: int = config.MAX_AGENT_TURNS,
              max_tokens: int = 2048,
              on_event: Optional[Callable[[dict], None]] = None,
              cancel_event: Optional[Any] = None) -> dict:
    """Drive the loop. ``messages`` is mutated in place (new turns appended).

    Returns::

        {
          "content": str | None,        # final assistant text (None if cap hit)
          "reasoning": str,
          "model": "e4b" | "12b",       # model that produced the final answer
          "turns": int,
          "escalated": bool,
          "usage": {prompt, completion, total},   # summed across turns
          "new_messages": [...],        # turns appended this call (to persist)
          "stopped": bool,              # True if cancelled mid-flight (partial text)
        }

    ``cancel_event`` (a ``threading.Event``) is forwarded to the streaming model
    call; when a model call comes back ``stopped`` (or the event is already set),
    the loop halts and returns the partial answer with ``"stopped": True``.
    """
    new_messages: list[dict] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    escalated = False
    cur_thinking = thinking

    for turn in range(max_turns):
        # Pre-call cancel check (e.g. Stop arrived between turns).
        if cancel_event is not None and cancel_event.is_set():
            return {
                "content": None, "reasoning": "", "model": manager.active,
                "turns": turn, "escalated": escalated, "usage": usage_total,
                "new_messages": new_messages, "stopped": True,
            }

        # --- auto-compaction (spec §7.2) ---
        if llm_client.approx_tokens(messages) > config.CTX * config.COMPACT_THRESHOLD:
            _emit(on_event, type="compact")
            removed = compact(messages)
            _emit(on_event, type="compacted", removed=removed)

        # --- assemble advertised tools ---
        tools = list(registry.schemas(tool_names))
        if allow_escalation:
            if manager.active == config.E4B:
                tools.append(ESCALATE_TOOL)
            elif manager.active == config.B12:
                tools.append(DESCALATE_TOOL)

        _emit(on_event, type="generating", model=manager.active, thinking=cur_thinking)
        with manager.generating(cur_thinking):
            resp = llm_client.chat(
                manager.active_base_url(), manager.model_name(), messages,
                tools=tools or None, thinking=cur_thinking, max_tokens=max_tokens,
                stream=True, cancel_event=cancel_event)

        u = resp["usage"]
        for k in usage_total:
            usage_total[k] += u.get(k, 0)

        stopped = bool(resp.get("stopped")
                       or (cancel_event is not None and cancel_event.is_set()))

        tool_calls = resp.get("tool_calls")
        if stopped or not tool_calls:
            # Final answer, or a cancellation: return the (possibly partial) text.
            return {
                "content": resp.get("content"),
                "reasoning": resp.get("reasoning", ""),
                "model": manager.active,
                "turns": turn + 1,
                "escalated": escalated,
                "usage": usage_total,
                "new_messages": new_messages,
                "stopped": stopped,
            }

        # Persist the assistant tool-call message.
        assistant_msg = {"role": "assistant",
                         "content": resp.get("content"),
                         "tool_calls": tool_calls}
        messages.append(assistant_msg)
        new_messages.append(assistant_msg)

        # Execute each requested tool.
        for call in tool_calls:
            fn = call.get("function", {}) or {}
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            call_id = call.get("id", name)
            _emit(on_event, type="tool_call", name=name)

            if name == "escalate_to_12b":
                result = _do_escalate(args, on_event)
                escalated = True
                cur_thinking = _wants_thinking(args, default=cur_thinking)
            elif name == "descalate":
                result = _do_descalate(on_event)
                cur_thinking = False
            else:
                result = registry.call(name, args)
            _emit(on_event, type="tool_result", name=name)

            tool_msg = {"role": "tool", "tool_call_id": call_id, "content": str(result)}
            messages.append(tool_msg)
            new_messages.append(tool_msg)

        # If we just descalated/escalated and the model produced no text, loop again.

    # Turn cap reached without a final answer (spec §7.1: triggers escalation upstream).
    return {
        "content": None,
        "reasoning": "",
        "model": manager.active,
        "turns": max_turns,
        "escalated": escalated,
        "usage": usage_total,
        "new_messages": new_messages,
        "stopped": False,
    }


# --------------------------------------------------------------------------- #
# Control-tool actions
# --------------------------------------------------------------------------- #
def _wants_thinking(args: Any, default: bool) -> bool:
    import json
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return default
    return bool((args or {}).get("thinking", default))


def _do_escalate(args: Any, on_event) -> str:
    _emit(on_event, type="escalate")
    try:
        manager.escalate()
    except Exception as e:  # noqa: BLE001
        return f"error: escalation failed: {e}"
    # Seed the 12B with the descalation policy.
    return ("escalated to 12B. " + DESCALATE_SYSTEM_HINT)


def _do_descalate(on_event) -> str:
    _emit(on_event, type="descalate")
    try:
        manager.descalate()
    except Exception as e:  # noqa: BLE001
        return f"error: descalation failed: {e}"
    return "descalated to E4B."


# --------------------------------------------------------------------------- #
# Compaction (spec §7.2)
# --------------------------------------------------------------------------- #
def compact(messages: list[dict], keep_last: int = 4) -> int:
    """Summarise older turns into a single system note, preserving tool pairs.

    Mutates ``messages`` in place; returns the number of messages collapsed.
    Rules: keep leading system message(s); never split an assistant
    ``tool_calls`` from its following ``tool`` results; thinking forced OFF so
    the summary doesn't leak into reasoning_content; raw image parts dropped.
    """
    # Leading system messages are always kept verbatim.
    head = 0
    while head < len(messages) and messages[head].get("role") == "system":
        head += 1

    if len(messages) - head <= keep_last:
        return 0

    boundary = len(messages) - keep_last
    # Don't start the kept tail on a dangling tool result.
    while boundary < len(messages) and messages[boundary].get("role") == "tool":
        boundary += 1
    # Don't end the summarised middle on an assistant that has tool_calls whose
    # results live in the tail.
    if boundary - 1 >= head and messages[boundary - 1].get("tool_calls"):
        boundary -= 1
        while boundary < len(messages) and messages[boundary].get("role") == "tool":
            boundary += 1

    middle = messages[head:boundary]
    if not middle:
        return 0

    transcript = _render_for_summary(middle)
    summary_prompt = [
        {"role": "system",
         "content": "다음 대화 일부를 한국어로 간결히 요약하라. 핵심 사실·결정·미해결 항목만 보존하고 "
                    "불필요한 인사말은 제거하라. 코드/수치는 정확히 유지하라."},
        {"role": "user", "content": transcript[:12000]},
    ]
    try:
        with manager.generating(False):
            resp = llm_client.chat(manager.active_base_url(), manager.model_name(),
                                   summary_prompt, thinking=False, max_tokens=700)
        summary = resp.get("content") or "(요약 실패)"
    except Exception as e:  # noqa: BLE001 — never let compaction crash the turn
        summary = f"(이전 대화 요약 생성 실패: {e})"

    note = {"role": "system", "content": "[이전 대화 요약]\n" + summary}
    messages[head:boundary] = [note]
    return len(middle) - 1


def _render_for_summary(msgs: list[dict]) -> str:
    lines = []
    for m in msgs:
        role = m.get("role", "?")
        content = m.get("content")
        if content is None and m.get("tool_calls"):
            calls = ", ".join((c.get("function", {}) or {}).get("name", "?")
                              for c in m["tool_calls"])
            content = f"[도구 호출: {calls}]"
        if isinstance(content, list):  # multimodal parts -> keep text only
            content = " ".join(p.get("text", "") for p in content
                               if isinstance(p, dict) and p.get("type") == "text")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)

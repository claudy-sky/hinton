"""System prompts.  Switching UI mode only swaps the system prompt — the model
server is *not* restarted (spec §8)."""
from __future__ import annotations

import json

from . import config, db

_BASE = (
    "You are Hinton, a local, offline AI study assistant for students at the "
    "Sejong Academy of Science and Arts (SASA). "
    "Reply in the same language the user writes in; default to English. "
    "Write mathematics in LaTeX ($...$, $$...$$), code in fenced code blocks, "
    "diagrams in ```mermaid blocks when they help, and function graphs with a "
    "[PLOT: expression] tag. Explain accurately and step by step so the answer "
    "supports learning."
)

CHAT = _BASE + (
    "\n\n[Chat mode] General-purpose study conversation. When useful, use the "
    "web search, academic search, deep research, and image generation tools. "
    "For hard reasoning or multi-step work, switch to the 12B model with the "
    "escalate_to_12b tool."
)

NOTEBOOK = _BASE + (
    "\n\n[Notebook mode] Answer only within the source scope of the selected "
    "notebook (subject). Ground every answer in the provided source excerpts and "
    "cite the supporting location (e.g. p.42, 3:20). Do not guess about anything "
    "that is not in the sources; instead state 'not in the sources'."
)

CODE = _BASE + (
    "\n\n[Code mode] You are a coding study partner. Provide runnable code; the "
    "user executes Python (Pyodide), JS, and C/C++ directly in a sandbox. "
    "Comment the code clearly and explain how to run it along with the expected "
    "output."
)

_MODE_PROMPTS = {"chat": CHAT, "notebook": NOTEBOOK, "code": CODE}


def memory_preamble() -> str:
    """Inject cross-session user facts ahead of the system prompt (spec §20.1)."""
    rows = db.list_memory()
    if not rows:
        return ""
    lines = "\n".join(f"- {r['key']}: {r['value']}" for r in rows[:40])
    return ("[User memory — facts remembered from earlier sessions]\n"
            + lines + "\n\n")


# --------------------------------------------------------------------------- #
# Global preferences + project/folder context preambles (Hinton)
# --------------------------------------------------------------------------- #
_SETTINGS_PATH = config.DATA_DIR / "settings.json"

# Tone enum -> concrete instruction sentence.  Keys MUST match the shared
# contract exactly: default, friendly, formal, concise, detailed, socratic,
# encouraging.
TONE_INSTRUCTIONS = {
    "default": "",
    "friendly": "Use a warm, friendly, and approachable tone.",
    "formal": "Use a formal, professional tone.",
    "concise": "Be concise and to the point.",
    "detailed": "Give thorough, detailed explanations with examples.",
    "socratic": ("Guide with leading questions rather than giving direct "
                 "answers."),
    "encouraging": ("Be encouraging and supportive; motivate the learner and "
                    "celebrate progress."),
}


def tone_instruction(tone: str) -> str:
    """Map a tone enum value to its instruction sentence ('' if none/unknown)."""
    return TONE_INSTRUCTIONS.get((tone or "").strip().lower(), "")


def _read_settings() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def preferences_preamble() -> str:
    """System text built from the global preferences in settings.json
    (pref_about / pref_style / pref_tone).  Returns '' if all are empty."""
    s = _read_settings()
    about = (s.get("pref_about") or "").strip()
    style = (s.get("pref_style") or "").strip()
    tone = (s.get("pref_tone") or "").strip()
    tone_line = tone_instruction(tone)

    lines: list[str] = []
    if about:
        lines.append("About the user: " + about)
    if style:
        lines.append("Preferred response style: " + style)
    if tone_line:
        lines.append(tone_line)
    if not lines:
        return ""
    return "[User preferences]\n" + "\n".join(lines)


def folder_preamble(folder_id) -> str:
    """Walk the folder chain ROOT->LEAF: concatenate each folder's instructions,
    then append folder_context text for the folders in the chain.  The combined
    context block is truncated to ~8000 chars.  Returns '' if folder_id falsy."""
    if not folder_id:
        return ""
    chain = db.folder_ancestors(int(folder_id))
    if not chain:
        return ""

    instr_parts: list[str] = []
    for f in chain:  # already root-first
        instr = (f.get("instructions") or "").strip()
        if instr:
            label = f.get("name") or f"folder {f.get('id')}"
            instr_parts.append(f"[{label}] {instr}")

    context_parts: list[str] = []
    for f in chain:
        for row in db.get_folder_context_text(f["id"]):
            text = (row.get("text") or "").strip()
            if text:
                name = row.get("name") or "context"
                context_parts.append(f"--- {name} ---\n{text}")

    sections: list[str] = []
    if instr_parts:
        sections.append("[Project instructions]\n" + "\n\n".join(instr_parts))
    if context_parts:
        combined = "\n\n".join(context_parts)
        if len(combined) > 8000:
            combined = combined[:8000] + "\n…(project context truncated)…"
        sections.append("[Project reference material]\n" + combined)
    return "\n\n".join(sections)


def system_message(mode: str, extra: str = "") -> dict:
    base = _MODE_PROMPTS.get(mode, CHAT)
    content = memory_preamble() + base
    if extra:
        content += "\n\n" + extra
    return {"role": "system", "content": content}

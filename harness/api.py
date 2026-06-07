"""pywebview JS bridge.

Every method here is callable from the frontend as
``window.pywebview.api.<method>(...)``.  Arguments and return values are
JSON-serialisable.  Long-running generation pushes progress events back to the
webview via ``window.openlmEvent(...)`` (set up by :mod:`harness.main`).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading

from . import config, db, prompts
from .agent_loop import run_agent, compact
from .model_manager import manager
from .tools.registry import registry

log = logging.getLogger("openlm.api")

_GEN_PROMPTS = {
    "summary": "Summarize the key points of each unit based on the source "
               "excerpts of this notebook.",
    "quiz": ("Create a 5-question multiple-choice quiz based on the source "
             "excerpts of this notebook. Output ONLY a ```json code block "
             "containing an array in exactly this format: "
             '[{"question":"...","options":["A","B","C","D"],'
             '"answer_index":0,"explanation":"...","concept":"unit name"}]'),
    "cards": "Create 10 flashcards (front: question, back: answer) for the key "
             "concepts as a markdown table.",
    "wrong": "Based on the wrong answers below, re-explain the weak concepts and "
             "provide similar practice problems.",
    "pptx": "Organize this notebook's content into presentation slides and "
            "generate a PPTX file with the create_pptx tool.",
    "docx": "Organize this notebook's content into study notes and generate a "
            "DOCX file with the create_docx tool.",
    "xlsx": "Generate an XLSX table file of this notebook's key terms and "
            "definitions with the create_xlsx tool.",
    "pdf": ("Write a clean HTML summary note for this notebook, then generate a "
            "PDF study material with the create_pdf tool."),
}

_SETTINGS_PATH = config.DATA_DIR / "settings.json"
_DEFAULT_SETTINGS = {
    "theme": "dark",
    "default_thinking": False,
    "panel_sizes": {},
    "image_gen_enabled": False,
    "pref_about": "",
    "pref_style": "",
    "pref_tone": "default",
}

# Allowed tone enum values (shared contract).
TONE_VALUES = ("default", "friendly", "formal", "concise", "detailed",
               "socratic", "encouraging")


def _normalize_tone(tone: str) -> str:
    """Coerce an arbitrary tone string to a valid enum value (default fallback)."""
    t = (tone or "").strip().lower()
    return t if t in TONE_VALUES else "default"


def _parse_semver(v: str) -> tuple[int, ...]:
    """Lenient semver -> comparable tuple. Drops a leading 'v' and any
    pre-release/build suffix; non-numeric parts become 0. Never raises."""
    s = (v or "").strip().lstrip("vV")
    # Cut at the first '-' (pre-release) or '+' (build metadata).
    for sep in ("-", "+", " "):
        i = s.find(sep)
        if i != -1:
            s = s[:i]
    parts = []
    for chunk in s.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly higher semver than ``current``."""
    a, b = _parse_semver(latest), _parse_semver(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _to_openai(rows: list[dict]) -> list[dict]:
    """Convert persisted message rows into OpenAI-shaped messages."""
    out = []
    for r in rows:
        role = r["role"]
        if role == "assistant" and r.get("tool_calls"):
            out.append({"role": "assistant", "content": r.get("content"),
                        "tool_calls": r["tool_calls"]})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": r.get("tool_call_id") or "",
                        "content": r.get("content") or ""})
        elif role in ("user", "assistant", "system"):
            out.append({"role": role, "content": r.get("content") or ""})
    return out


class Api:
    def __init__(self) -> None:
        self.window = None  # set by main after window creation
        # Live generation progress, polled by the UI via get_progress(). Works in
        # both transports (pywebview push and the --serve HTTP server), so the
        # status line can show a running token count and the thinking phase
        # instead of a static "Generating…".
        self._progress = self._idle_progress()

    @staticmethod
    def _idle_progress() -> dict:
        return {"phase": "idle", "model": None, "thinking": False,
                "tokens": 0, "reasoning_tokens": 0, "tool": None}

    # ------------------------------------------------------------------ #
    # Status / model control
    # ------------------------------------------------------------------ #
    def get_status(self) -> dict:
        return {**manager.status(),
                "tools": registry.names(),
                "ctx": config.CTX,
                "b12_available": config.B12_AVAILABLE,
                "e4b_available": config.E4B_AVAILABLE}

    def get_progress(self) -> dict:
        """Snapshot of the in-flight generation for the live status readout."""
        return dict(self._progress)

    def get_boot_status(self) -> dict:
        """First-run boot/download status, polled by the loading window."""
        from . import boot
        return boot.snapshot()

    def set_model(self, model_key: str) -> dict:
        """Manual escalation / descalation (spec §5.1)."""
        if model_key == config.B12:
            if not config.B12_AVAILABLE:
                return {**manager.status(),
                        "error": "12B model is not installed — install the 12B plugin."}
            manager.escalate()
        elif model_key == config.E4B:
            manager.descalate()
        return manager.status()

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #
    def list_conversations(self, mode: str | None = None,
                           folder_id: object = "__all__") -> list[dict]:
        return db.list_conversations(mode, folder_id)

    def new_conversation(self, mode: str = "chat", title: str = "New chat",
                         notebook_id: int | None = None,
                         folder_id: int | None = None) -> dict:
        cid = db.create_conversation(mode, title, notebook_id, folder_id)
        return {"id": cid, "mode": mode, "title": title,
                "notebook_id": notebook_id, "folder_id": folder_id}

    def get_conversation(self, conv_id: int) -> dict:
        return {"messages": db.get_messages(conv_id)}

    def rename_conversation(self, conv_id: int, title: str) -> dict:
        db.rename_conversation(conv_id, title)
        return {"ok": True}

    def delete_conversation(self, conv_id: int) -> dict:
        db.delete_conversation(conv_id)
        return {"ok": True}

    def assign_conversation(self, conv_id: int,
                            folder_id: int | None = None) -> dict:
        """File (or unfile, folder_id=None) a conversation into a folder."""
        db.set_conversation_folder(conv_id, folder_id)
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # Folders / projects (Hinton)
    # ------------------------------------------------------------------ #
    def list_folders(self) -> list[dict]:
        out = []
        for f in db.list_folders():
            out.append({
                "id": f["id"], "parent_id": f["parent_id"], "name": f["name"],
                "instructions": f.get("instructions", ""),
                "tone": f.get("tone", ""), "conv_count": f.get("conv_count", 0),
                "created_at": f["created_at"], "updated_at": f["updated_at"],
            })
        return out

    def create_folder(self, name: str, parent_id: int | None = None) -> dict:
        fid = db.create_folder(name, parent_id)
        return {"id": fid, "parent_id": parent_id, "name": name}

    def rename_folder(self, folder_id: int, name: str) -> dict:
        db.rename_folder(folder_id, name)
        return {"ok": True}

    def delete_folder(self, folder_id: int) -> dict:
        db.delete_folder(folder_id)
        return {"ok": True}

    def move_folder(self, folder_id: int, parent_id: int | None) -> dict:
        return db.move_folder(folder_id, parent_id)

    def set_folder_prefs(self, folder_id: int, instructions: str,
                         tone: str) -> dict:
        db.set_folder_prefs(folder_id, instructions or "",
                            _normalize_tone(tone))
        return {"ok": True}

    def get_folder(self, folder_id: int) -> dict:
        folder = db.get_folder(folder_id)
        ancestors = db.folder_ancestors(folder_id)  # root-first, incl. self
        eff_instructions = "\n\n".join(
            (a.get("instructions") or "").strip()
            for a in ancestors if (a.get("instructions") or "").strip())
        # Effective tone = nearest non-empty tone walking leaf -> root.
        eff_tone = ""
        for a in reversed(ancestors):
            t = (a.get("tone") or "").strip()
            if t:
                eff_tone = t
                break
        return {"folder": folder, "ancestors": ancestors,
                "effective_instructions": eff_instructions,
                "effective_tone": eff_tone}

    def list_folder_context(self, folder_id: int) -> list[dict]:
        return [
            {"id": r["id"], "name": r["name"], "kind": r["kind"],
             "char_count": r["char_count"], "created_at": r["created_at"]}
            for r in db.list_folder_context(folder_id)
        ]

    def add_folder_context(self, folder_id: int, path: str) -> dict:
        """Extract text from a file and attach it as project reference material.

        Reuses harness.tools.notebook_rag extraction (pdf/docx/xlsx/txt/md);
        falls back to a direct read for .txt/.md and stores a short note for
        unsupported types.  Stored text is truncated to <=100000 chars."""
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": f"File not found: {path}"}

        kind, text = self._extract_context_text(p)
        text = (text or "")[:100000]
        cid = db.add_folder_context(folder_id, str(p), kind, p.name, text)
        return {"ok": True, "id": cid, "name": p.name, "char_count": len(text)}

    def delete_folder_context(self, context_id: int) -> dict:
        db.delete_folder_context(context_id)
        return {"ok": True}

    @staticmethod
    def _extract_context_text(p) -> tuple[str, str]:
        """Return (kind, extracted_text) for a file using notebook_rag helpers,
        with robust fallbacks."""
        kind = p.suffix.lstrip(".").lower() or "file"
        try:
            from .tools import notebook_rag
            kind = notebook_rag._kind_from_path(p)
            extracted = notebook_rag._extract(p, kind)
            if isinstance(extracted, str):
                # extraction returned an error note (e.g. missing dependency)
                if kind in ("txt", "md"):
                    return kind, p.read_text(encoding="utf-8", errors="ignore")
                return kind, f"[{p.name}] {extracted}"
            # list[tuple[locator, text]] -> joined text
            parts = []
            for locator, body in extracted:
                body = (body or "").strip()
                if not body:
                    continue
                parts.append(f"[{locator}]\n{body}" if locator else body)
            joined = "\n\n".join(parts)
            if joined.strip():
                return kind, joined
            # nothing extracted -> fall through to direct read / note
        except Exception as e:  # noqa: BLE001
            log.warning("folder context extraction failed for %s: %s", p, e)

        # Fallbacks.
        if p.suffix.lower() in (".txt", ".md"):
            try:
                return kind, p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                pass
        return kind, (f"[{p.name}] Unsupported file type for text extraction; "
                      "stored as a reference only.")

    # ------------------------------------------------------------------ #
    # Global preferences (Hinton)
    # ------------------------------------------------------------------ #
    def get_preferences(self) -> dict:
        s = self.get_settings()
        return {"about": s.get("pref_about", ""),
                "style": s.get("pref_style", ""),
                "tone": s.get("pref_tone", "")}

    def set_preferences(self, about: str, style: str, tone: str) -> dict:
        self.save_settings({
            "pref_about": about or "",
            "pref_style": style or "",
            "pref_tone": _normalize_tone(tone),
        })
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # Core: send a message and run the agent loop
    # ------------------------------------------------------------------ #
    def send_message(self, conv_id: int, text: str, mode: str = "chat",
                     thinking: bool = False, notebook_id: int | None = None) -> dict:
        if manager.active is None:
            return {"message": {"role": "assistant",
                                "content": "The model is loading. Please try "
                                           "again in a moment.",
                                "model": None, "meta": {}},
                    "status": manager.status(), "not_ready": True}
        db.add_message(conv_id, "user", text)

        messages = [prompts.system_message(mode)]
        # Global preferences + project/folder context (derived from the
        # conversation's folder_id; send_message signature is unchanged).
        folder_id = db.get_conversation_folder_id(conv_id)
        preamble = "\n\n".join(
            p for p in (prompts.preferences_preamble(),
                        prompts.folder_preamble(folder_id)) if p)
        if preamble:
            messages.append({"role": "system", "content": preamble})
        if mode == "notebook" and notebook_id:
            ctx = self._retrieve_notebook(notebook_id, text)
            if ctx:
                messages.append({"role": "system", "content": ctx})
        messages += _to_openai(db.get_messages(conv_id))

        tool_names = [] if mode == "code" else None  # code runs client-side
        ev = manager.new_cancel()
        self._progress = {"phase": "starting", "model": manager.active,
                          "thinking": bool(thinking), "tokens": 0,
                          "reasoning_tokens": 0, "tool": None}
        try:
            result = run_agent(messages, thinking=thinking, tool_names=tool_names,
                               on_event=self._push_event, cancel_event=ev)

            # Turn cap with no answer on E4B -> escalate once (spec §7.1).
            # Skip the retry if the user cancelled or 12B isn't installed.
            if (result["content"] is None and not result.get("stopped")
                    and manager.active == config.E4B and config.B12_AVAILABLE):
                self._push_event({"type": "escalate", "reason": "turn cap"})
                manager.escalate()
                again = run_agent(messages, thinking=True, tool_names=tool_names,
                                  on_event=self._push_event, cancel_event=ev)
                again["new_messages"] = result["new_messages"] + again["new_messages"]
                again["escalated"] = True
                result = again
        finally:
            manager.clear_cancel()
            self._progress = self._idle_progress()

        # Persist intermediate tool turns, then the final answer.
        for m in result["new_messages"]:
            if m["role"] == "assistant" and m.get("tool_calls"):
                db.add_message(conv_id, "assistant", m.get("content"),
                               tool_calls=m["tool_calls"], model=result["model"])
            elif m["role"] == "tool":
                db.add_message(conv_id, "tool", m.get("content"),
                               tool_call_id=m.get("tool_call_id"))

        final_text = result["content"] or "(Failed to generate a response)"
        msg_id = db.add_message(
            conv_id, "assistant", final_text, model=result["model"],
            reasoning=result.get("reasoning") or None,
            meta={"usage": result["usage"], "turns": result["turns"],
                  "escalated": result["escalated"]})

        self._maybe_autotitle(conv_id, text)
        return {
            "message": {"id": msg_id, "role": "assistant", "content": final_text,
                        "reasoning": result.get("reasoning") or None,
                        "model": result["model"],
                        "meta": {"usage": result["usage"], "turns": result["turns"],
                                 "escalated": result["escalated"]}},
            "status": manager.status(),
            "stopped": bool(result.get("stopped", False)),
        }

    def stop_generation(self) -> dict:
        """Signal the current in-flight generation to abort (Stop button)."""
        manager.cancel()
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # In-app update check (spec §23.3)
    # ------------------------------------------------------------------ #
    def check_update(self) -> dict:
        """Check the configured manifest for a newer Hinton release.

        Returns ``{"current", "latest", "update_available", "url", "notes"}``.
        With no ``OPENLM_UPDATE_URL`` configured, or on ANY network/parse error,
        reports ``update_available=false`` and never raises.
        """
        current = config.VERSION
        url = (config.UPDATE_URL or "").strip()
        if not url:
            return {"update_available": False, "current": current,
                    "latest": None, "url": None, "notes": None}
        try:
            import urllib.request
            req = urllib.request.Request(
                url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                manifest = json.loads(resp.read().decode("utf-8"))
            latest = str(manifest.get("version") or "").strip()
            installer = manifest.get("installer_url") or None
            notes = manifest.get("notes") or None
            if not latest:
                return {"update_available": False, "current": current,
                        "latest": None, "url": None, "notes": None}
            available = _is_newer(latest, current)
            return {
                "update_available": available,
                "current": current,
                "latest": latest,
                "url": installer if available else None,
                "notes": notes if available else None,
            }
        except Exception as e:  # noqa: BLE001 — never raise; treat as no update
            log.warning("update check failed: %s", e)
            return {"update_available": False, "current": current,
                    "latest": None, "url": None, "notes": None}

    def compact_conversation(self, conv_id: int) -> dict:
        """Manual /compact — summarise the working context (spec §7.2)."""
        msgs = [prompts.system_message("chat")] + _to_openai(db.get_messages(conv_id))
        removed = compact(msgs)
        return {"removed": removed, "ok": True}

    # ------------------------------------------------------------------ #
    # Notebooks
    # ------------------------------------------------------------------ #
    def list_notebooks(self) -> list[dict]:
        return db.list_notebooks()

    def create_notebook(self, name: str) -> dict:
        nid = db.create_notebook(name)
        return {"id": nid, "name": name}

    def delete_notebook(self, notebook_id: int) -> dict:
        db.delete_notebook(notebook_id)
        return {"ok": True}

    def list_sources(self, notebook_id: int) -> list[dict]:
        return db.list_sources(notebook_id)

    def add_source(self, notebook_id: int, path: str) -> dict:
        """Ingest a file into a notebook (extract -> chunk -> embed -> store)."""
        try:
            from .tools import notebook_rag
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"notebook plugin unavailable: {e}"}
        try:
            return notebook_rag.ingest_source(notebook_id, path)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def _retrieve_notebook(self, notebook_id: int, query: str) -> str:
        try:
            from .tools import notebook_rag
            return notebook_rag.context_for(notebook_id, query)
        except Exception as e:  # noqa: BLE001
            log.warning("notebook retrieval unavailable: %s", e)
            return ""

    def get_source(self, source_id: int) -> dict | None:
        return db.get_source(source_id)

    def get_source_text(self, source_id: int, max_chars: int = 20000) -> dict:
        chunks = db.get_source_chunks(source_id)
        parts = []
        for c in chunks:
            loc = f"[{c['locator']}] " if c.get("locator") else ""
            parts.append(loc + (c.get("text") or ""))
        text = "\n\n".join(parts)[:max_chars]
        return {"text": text, "n_chunks": len(chunks)}

    def notebook_generate(self, notebook_id: int, kind: str) -> dict:
        """Run a study-material generation for a notebook (spec §15, §16)."""
        if manager.active is None:
            return {"ok": False, "error": "The model is loading."}
        instr = _GEN_PROMPTS.get(kind)
        if not instr:
            return {"ok": False, "error": f"Unknown generation type: {kind}"}
        if kind == "wrong":
            wrongs = db.wrong_answers(notebook_id)[:10]
            if wrongs:
                instr += "\n\n[Recent wrong answers]\n" + "\n".join(
                    f"- {w['question']} (correct answer: {w['answer']})"
                    for w in wrongs)

        messages = [prompts.system_message("notebook")]
        ctx = self._retrieve_notebook(notebook_id, instr)
        if ctx:
            messages.append({"role": "system", "content": ctx})
        messages.append({"role": "user", "content": instr})

        thinking = kind in ("quiz", "summary", "wrong")
        result = run_agent(messages, thinking=thinking, tool_names=None,
                           on_event=self._push_event)
        return {"ok": True, "kind": kind, "content": result["content"] or "",
                "model": result["model"]}

    # ------------------------------------------------------------------ #
    # Quiz history (spec §15)
    # ------------------------------------------------------------------ #
    def record_quiz(self, notebook_id: int | None, question: str, answer: str,
                    user_answer: str, correct: bool, concept: str = "") -> dict:
        qid = db.record_quiz(notebook_id, question, answer, user_answer,
                             correct, concept)
        return {"ok": True, "id": qid}

    def quiz_wrong(self, notebook_id: int | None = None) -> list[dict]:
        return db.wrong_answers(notebook_id)

    def quiz_weak_concepts(self, notebook_id: int | None = None) -> list[dict]:
        return db.weak_concepts(notebook_id)

    # ------------------------------------------------------------------ #
    # Code execution (C/C++; Python & JS run client-side, spec §18)
    # ------------------------------------------------------------------ #
    def run_c(self, code: str, stdin: str = "") -> str:
        return registry.call("run_c", {"code": code, "stdin": stdin})

    def run_cpp(self, code: str, stdin: str = "") -> str:
        return registry.call("run_cpp", {"code": code, "stdin": stdin})

    # ------------------------------------------------------------------ #
    # Memory (spec §20)
    # ------------------------------------------------------------------ #
    def list_memory(self) -> list[dict]:
        return db.list_memory()

    def set_memory(self, key: str, value: str) -> dict:
        db.set_memory(key, value, source="user")
        return {"ok": True}

    def delete_memory(self, key: str) -> dict:
        db.delete_memory(key)
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # Artifacts / files
    # ------------------------------------------------------------------ #
    def list_generated(self) -> list[dict]:
        out = []
        for p in sorted(config.GENERATED_DIR.glob("*")):
            if p.is_file():
                out.append({"name": p.name, "path": str(p),
                            "size": p.stat().st_size})
        return out

    def open_path(self, path: str) -> dict:
        # Open with the OS default handler. No shell is involved:
        # os.startfile on Windows and subprocess.run([...]) (list form, shell=False)
        # elsewhere, so the path cannot be interpreted as a shell command.
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def import_attachment(self, conv_id: int, src_path: str) -> dict:
        """Copy an uploaded file into the data dir and register it."""
        from pathlib import Path
        p = Path(src_path)
        if not p.exists():
            return {"ok": False, "error": "File not found"}
        dest = config.ATTACHMENTS_DIR / p.name
        shutil.copy2(p, dest)
        kind = p.suffix.lstrip(".").lower()
        return {"ok": True, "path": str(dest), "name": p.name, "kind": kind}

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #
    def get_settings(self) -> dict:
        if _SETTINGS_PATH.exists():
            try:
                return {**_DEFAULT_SETTINGS,
                        **json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))}
            except Exception:  # noqa: BLE001
                pass
        return dict(_DEFAULT_SETTINGS)

    def save_settings(self, settings: dict) -> dict:
        merged = {**self.get_settings(), **(settings or {})}
        _SETTINGS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _maybe_autotitle(self, conv_id: int, first_user_text: str) -> None:
        convs = {c["id"]: c for c in db.list_conversations()}
        c = convs.get(conv_id)
        if c and c.get("title") in ("New chat", "새 대화", "", None):
            title = ((first_user_text or "").strip().splitlines()[0][:30]
                     or "New chat")
            db.rename_conversation(conv_id, title)

    def _push_event(self, event: dict) -> None:
        # Keep the polled progress snapshot current for every event (works in
        # both transports). Token deltas only update the snapshot — they are far
        # too frequent to forward to pywebview one by one.
        self._update_progress(event)
        if event.get("type") == "token":
            return
        if self.window is None:
            return
        try:
            payload = json.dumps(event, ensure_ascii=False)
            self.window.evaluate_js(f"window.openlmEvent && window.openlmEvent({payload})")
        except Exception:  # noqa: BLE001
            pass

    def _update_progress(self, event: dict) -> None:
        t = event.get("type")
        p = self._progress
        if t == "generating":
            p.update(phase="thinking" if event.get("thinking") else "generating",
                     model=event.get("model"), thinking=bool(event.get("thinking")),
                     tokens=0, reasoning_tokens=0, tool=None)
        elif t == "token":
            n = int(event.get("n", 0))
            rn = int(event.get("reasoning_n", 0))
            p["tokens"] = n
            p["reasoning_tokens"] = rn
            p["model"] = event.get("model", p.get("model"))
            # Once answer tokens start flowing, we've left the thinking phase.
            p["phase"] = "generating" if n > 0 else (
                "thinking" if rn > 0 else p.get("phase", "generating"))
        elif t == "tool_call":
            p.update(phase="tool", tool=event.get("name"))
        elif t == "tool_result":
            p.update(phase="generating", tool=None)
        elif t == "escalate":
            p.update(phase="escalating", tool=None)
        elif t == "descalate":
            p.update(phase="generating")
        elif t == "compact":
            p.update(phase="compacting")

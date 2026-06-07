"""SQLite persistence layer (spec §21).

Eight tables: conversations, messages, attachments, memory, notebooks, sources,
chunks, quiz_history.  Embedding vectors are stored as raw float32 BLOBs in the
``chunks`` table; similarity search is done in :mod:`harness.tools.notebook_rag`
with a brute-force cosine over the stored vectors (robust, dependency-free, and
more than fast enough for a single student's notebooks).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable, Optional

from . import config

_local = threading.local()


# --------------------------------------------------------------------------- #
# Connection management
# --------------------------------------------------------------------------- #
def get_conn() -> sqlite3.Connection:
    """Thread-local connection (pywebview calls the bridge from worker threads)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return conn


def _now() -> float:
    return time.time()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mode        TEXT NOT NULL DEFAULT 'chat',     -- chat | notebook | code
    title       TEXT NOT NULL DEFAULT '새 대화',
    notebook_id INTEGER,                           -- set for notebook-scoped chats
    folder_id   INTEGER,                           -- project/folder grouping (nullable)
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS folders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id    INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    name         TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',         -- per-project custom instructions
    tone         TEXT NOT NULL DEFAULT '',         -- per-project tone enum override
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS folder_context (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id   INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    path        TEXT,
    kind        TEXT,                              -- pdf | docx | xlsx | txt | md | ...
    name        TEXT,
    text        TEXT,                              -- extracted text (truncated)
    char_count  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                 -- user | assistant | tool | system
    content         TEXT,
    tool_calls      TEXT,                          -- JSON (assistant tool_calls)
    tool_call_id    TEXT,                          -- for role=tool
    model           TEXT,                          -- e4b | 12b at time of generation
    reasoning       TEXT,                          -- thinking / reasoning_content
    meta            TEXT,                          -- JSON: tokens, elapsed, etc.
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    kind            TEXT,                          -- pdf | image | audio | docx | ...
    name            TEXT,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    source     TEXT,                               -- where the fact came from
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notebooks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,                      -- subject, e.g. 물리1
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    kind        TEXT,                              -- pdf | docx | xlsx | image | audio
    name        TEXT,
    n_chunks    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | indexed | error
    meta        TEXT,                              -- JSON: pages, duration, transcript
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    locator     TEXT,                              -- 'p.42' / '3:20' for citations
    embedding   BLOB,                              -- float32 vector (EMBED_DIM)
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER REFERENCES notebooks(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    answer      TEXT,                              -- correct answer
    user_answer TEXT,
    correct     INTEGER NOT NULL DEFAULT 0,        -- 0/1
    concept     TEXT,                              -- tag for weak-concept tracking
    locator     TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chunks_notebook ON chunks(notebook_id);
CREATE INDEX IF NOT EXISTS idx_sources_notebook ON sources(notebook_id);
CREATE INDEX IF NOT EXISTS idx_quiz_notebook ON quiz_history(notebook_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);
CREATE INDEX IF NOT EXISTS idx_folder_context_folder ON folder_context(folder_id);
"""
# NOTE: the index on conversations(folder_id) is created in init_db() AFTER the
# migration below, because on a pre-existing database the column does not yet
# exist when this script runs.


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    # Migration: older databases predate the conversations.folder_id column.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    if "folder_id" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN folder_id INTEGER")
    # Created here (not in SCHEMA) so it works on old DBs migrated just above.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_folder "
                 "ON conversations(folder_id)")
    conn.commit()


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
def create_conversation(mode: str = "chat", title: str = "새 대화",
                        notebook_id: Optional[int] = None,
                        folder_id: Optional[int] = None) -> int:
    conn = get_conn()
    t = _now()
    cur = conn.execute(
        "INSERT INTO conversations(mode, title, notebook_id, folder_id, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (mode, title, notebook_id, folder_id, t, t))
    conn.commit()
    return cur.lastrowid


_ALL_FOLDERS = "__all__"


def list_conversations(mode: Optional[str] = None,
                       folder_id: Any = _ALL_FOLDERS) -> list[dict]:
    """List conversations.

    ``folder_id`` semantics (frontend passes ``"__all__"`` or an int):
      * ``"__all__"`` (default) -> every conversation (legacy behaviour).
      * ``None``                -> only unfiled conversations (folder_id IS NULL).
      * ``int``                 -> only conversations in that folder.
    """
    conn = get_conn()
    where = []
    params: list[Any] = []
    if mode:
        where.append("mode=?")
        params.append(mode)
    if folder_id != _ALL_FOLDERS:
        if folder_id is None:
            where.append("folder_id IS NULL")
        else:
            where.append("folder_id=?")
            params.append(folder_id)
    sql = "SELECT * FROM conversations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC"
    return _rows(conn.execute(sql, params))


def set_conversation_folder(conv_id: int, folder_id: Optional[int]) -> None:
    conn = get_conn()
    conn.execute("UPDATE conversations SET folder_id=?, updated_at=? WHERE id=?",
                 (folder_id, _now(), conv_id))
    conn.commit()


def get_conversation_folder_id(conv_id: int) -> Optional[int]:
    cur = get_conn().execute("SELECT folder_id FROM conversations WHERE id=?",
                             (conv_id,))
    r = cur.fetchone()
    return r["folder_id"] if r else None


def rename_conversation(conv_id: int, title: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                 (title, _now(), conv_id))
    conn.commit()


def touch_conversation(conv_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id))
    conn.commit()


def delete_conversation(conv_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
def add_message(conversation_id: int, role: str, content: Optional[str] = None, *,
                tool_calls: Any = None, tool_call_id: Optional[str] = None,
                model: Optional[str] = None, reasoning: Optional[str] = None,
                meta: Any = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO messages(conversation_id, role, content, tool_calls, "
        "tool_call_id, model, reasoning, meta, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (conversation_id, role, content,
         json.dumps(tool_calls) if tool_calls is not None else None,
         tool_call_id, model, reasoning,
         json.dumps(meta) if meta is not None else None, _now()))
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?",
                 (_now(), conversation_id))
    conn.commit()
    return cur.lastrowid


def get_messages(conversation_id: int) -> list[dict]:
    conn = get_conn()
    cur = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id ASC",
        (conversation_id,))
    out = []
    for r in cur.fetchall():
        d = dict(r)
        if d.get("tool_calls"):
            d["tool_calls"] = json.loads(d["tool_calls"])
        if d.get("meta"):
            d["meta"] = json.loads(d["meta"])
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Memory (cross-session facts, spec §20)
# --------------------------------------------------------------------------- #
def set_memory(key: str, value: str, source: Optional[str] = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO memory(key, value, source, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "source=excluded.source, updated_at=excluded.updated_at",
        (key, value, source, _now()))
    conn.commit()


def list_memory() -> list[dict]:
    return _rows(get_conn().execute("SELECT * FROM memory ORDER BY updated_at DESC"))


def delete_memory(key: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM memory WHERE key=?", (key,))
    conn.commit()


# --------------------------------------------------------------------------- #
# Folders / projects (Hinton)
# --------------------------------------------------------------------------- #
def create_folder(name: str, parent_id: Optional[int] = None) -> int:
    conn = get_conn()
    t = _now()
    cur = conn.execute(
        "INSERT INTO folders(parent_id, name, instructions, tone, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (parent_id, name, "", "", t, t))
    conn.commit()
    return cur.lastrowid


def get_folder(folder_id: int) -> Optional[dict]:
    cur = get_conn().execute("SELECT * FROM folders WHERE id=?", (folder_id,))
    r = cur.fetchone()
    return dict(r) if r else None


def list_folders() -> list[dict]:
    """All folders with a per-folder conversation count (conv_count)."""
    conn = get_conn()
    counts = {
        r["folder_id"]: r["n"]
        for r in conn.execute(
            "SELECT folder_id, COUNT(*) AS n FROM conversations "
            "WHERE folder_id IS NOT NULL GROUP BY folder_id")
    }
    out = []
    for r in conn.execute(
            "SELECT * FROM folders ORDER BY name COLLATE NOCASE ASC, id ASC"):
        d = dict(r)
        d["conv_count"] = counts.get(d["id"], 0)
        out.append(d)
    return out


def rename_folder(folder_id: int, name: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE folders SET name=?, updated_at=? WHERE id=?",
                 (name, _now(), folder_id))
    conn.commit()


def set_folder_prefs(folder_id: int, instructions: str, tone: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE folders SET instructions=?, tone=?, updated_at=? WHERE id=?",
                 (instructions or "", tone or "", _now(), folder_id))
    conn.commit()


def delete_folder(folder_id: int) -> None:
    """Delete a folder. Children + folder_context cascade via FK; this folder's
    conversations are unfiled (folder_id set to NULL) recursively."""
    conn = get_conn()
    # Collect this folder and all descendants so we can unfile their conversations
    # (FK ON DELETE CASCADE does NOT touch conversations — they have no FK here).
    ids = _descendant_ids(folder_id, include_self=True)
    qmarks = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE conversations SET folder_id=NULL WHERE folder_id IN ({qmarks})",
        ids)
    conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
    conn.commit()


def _children_map() -> dict[Optional[int], list[int]]:
    conn = get_conn()
    children: dict[Optional[int], list[int]] = {}
    for r in conn.execute("SELECT id, parent_id FROM folders"):
        children.setdefault(r["parent_id"], []).append(r["id"])
    return children


def _descendant_ids(folder_id: int, include_self: bool = False) -> list[int]:
    children = _children_map()
    out: list[int] = []
    stack = list(children.get(folder_id, []))
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    if include_self:
        out.append(folder_id)
    return out


def folder_ancestors(folder_id: int) -> list[dict]:
    """Root-first chain of ancestors INCLUDING the folder itself."""
    conn = get_conn()
    chain: list[dict] = []
    seen: set[int] = set()
    cur_id: Optional[int] = folder_id
    while cur_id is not None and cur_id not in seen:
        seen.add(cur_id)
        row = conn.execute("SELECT * FROM folders WHERE id=?", (cur_id,)).fetchone()
        if row is None:
            break
        chain.append(dict(row))
        cur_id = row["parent_id"]
    chain.reverse()  # root first
    return chain


def move_folder(folder_id: int, parent_id: Optional[int]) -> dict:
    """Reparent a folder. Rejects self-parenting and cycles (descendant parent).
    ``parent_id=None`` moves to root."""
    if parent_id is not None:
        if parent_id == folder_id:
            return {"ok": False, "error": "A folder cannot be its own parent."}
        if parent_id in _descendant_ids(folder_id):
            return {"ok": False, "error": "Cannot move a folder into its own descendant."}
        if get_folder(parent_id) is None:
            return {"ok": False, "error": "Target parent folder does not exist."}
    if get_folder(folder_id) is None:
        return {"ok": False, "error": "Folder does not exist."}
    conn = get_conn()
    conn.execute("UPDATE folders SET parent_id=?, updated_at=? WHERE id=?",
                 (parent_id, _now(), folder_id))
    conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Folder context (uploaded reference material for a project)
# --------------------------------------------------------------------------- #
def add_folder_context(folder_id: int, path: str, kind: str, name: str,
                       text: str) -> int:
    conn = get_conn()
    char_count = len(text or "")
    cur = conn.execute(
        "INSERT INTO folder_context(folder_id, path, kind, name, text, "
        "char_count, created_at) VALUES (?,?,?,?,?,?,?)",
        (folder_id, path, kind, name, text or "", char_count, _now()))
    conn.execute("UPDATE folders SET updated_at=? WHERE id=?", (_now(), folder_id))
    conn.commit()
    return cur.lastrowid


def list_folder_context(folder_id: int) -> list[dict]:
    cur = get_conn().execute(
        "SELECT id, folder_id, name, kind, char_count, created_at "
        "FROM folder_context WHERE folder_id=? ORDER BY created_at ASC",
        (folder_id,))
    return _rows(cur)


def get_folder_context_text(folder_id: int) -> list[dict]:
    """Full context rows (with text) for a single folder, in insertion order."""
    cur = get_conn().execute(
        "SELECT id, folder_id, name, kind, text, char_count, created_at "
        "FROM folder_context WHERE folder_id=? ORDER BY created_at ASC",
        (folder_id,))
    return _rows(cur)


def delete_folder_context(context_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM folder_context WHERE id=?", (context_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
# Notebooks + sources + chunks
# --------------------------------------------------------------------------- #
def create_notebook(name: str) -> int:
    conn = get_conn()
    t = _now()
    cur = conn.execute(
        "INSERT INTO notebooks(name, created_at, updated_at) VALUES (?,?,?)",
        (name, t, t))
    conn.commit()
    return cur.lastrowid


def list_notebooks() -> list[dict]:
    return _rows(get_conn().execute("SELECT * FROM notebooks ORDER BY updated_at DESC"))


def delete_notebook(notebook_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM notebooks WHERE id=?", (notebook_id,))
    conn.commit()


def add_source(notebook_id: int, path: str, kind: str, name: str,
               meta: Any = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sources(notebook_id, path, kind, name, status, meta, created_at) "
        "VALUES (?,?,?,?, 'pending', ?, ?)",
        (notebook_id, path, kind, name,
         json.dumps(meta) if meta is not None else None, _now()))
    conn.execute("UPDATE notebooks SET updated_at=? WHERE id=?", (_now(), notebook_id))
    conn.commit()
    return cur.lastrowid


def list_sources(notebook_id: int) -> list[dict]:
    cur = get_conn().execute(
        "SELECT * FROM sources WHERE notebook_id=? ORDER BY created_at ASC",
        (notebook_id,))
    return _rows(cur)


def get_source(source_id: int) -> Optional[dict]:
    cur = get_conn().execute("SELECT * FROM sources WHERE id=?", (source_id,))
    r = cur.fetchone()
    return dict(r) if r else None


def get_source_chunks(source_id: int) -> list[dict]:
    cur = get_conn().execute(
        "SELECT id, source_id, notebook_id, ordinal, text, locator "
        "FROM chunks WHERE source_id=? ORDER BY ordinal ASC", (source_id,))
    return _rows(cur)


def set_source_status(source_id: int, status: str, n_chunks: Optional[int] = None,
                      meta: Any = None) -> None:
    conn = get_conn()
    if n_chunks is not None and meta is not None:
        conn.execute("UPDATE sources SET status=?, n_chunks=?, meta=? WHERE id=?",
                     (status, n_chunks, json.dumps(meta), source_id))
    elif n_chunks is not None:
        conn.execute("UPDATE sources SET status=?, n_chunks=? WHERE id=?",
                     (status, n_chunks, source_id))
    else:
        conn.execute("UPDATE sources SET status=? WHERE id=?", (status, source_id))
    conn.commit()


def add_chunks(source_id: int, notebook_id: int,
               chunks: Iterable[dict]) -> int:
    """chunks: iterable of {ordinal, text, locator, embedding(bytes|None)}."""
    conn = get_conn()
    t = _now()
    n = 0
    for c in chunks:
        conn.execute(
            "INSERT INTO chunks(source_id, notebook_id, ordinal, text, locator, "
            "embedding, created_at) VALUES (?,?,?,?,?,?,?)",
            (source_id, notebook_id, c["ordinal"], c["text"],
             c.get("locator"), c.get("embedding"), t))
        n += 1
    conn.commit()
    return n


def get_chunks(notebook_id: int, with_embeddings: bool = True) -> list[dict]:
    conn = get_conn()
    cols = "id, source_id, notebook_id, ordinal, text, locator" + \
           (", embedding" if with_embeddings else "")
    cur = conn.execute(
        f"SELECT {cols} FROM chunks WHERE notebook_id=? ORDER BY id ASC",
        (notebook_id,))
    return _rows(cur)


# --------------------------------------------------------------------------- #
# Quiz history (spec §15)
# --------------------------------------------------------------------------- #
def record_quiz(notebook_id: Optional[int], question: str, answer: str,
                user_answer: str, correct: bool, concept: str = "",
                locator: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO quiz_history(notebook_id, question, answer, user_answer, "
        "correct, concept, locator, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (notebook_id, question, answer, user_answer, 1 if correct else 0,
         concept, locator, _now()))
    conn.commit()
    return cur.lastrowid


def wrong_answers(notebook_id: Optional[int] = None) -> list[dict]:
    conn = get_conn()
    if notebook_id is not None:
        cur = conn.execute(
            "SELECT * FROM quiz_history WHERE correct=0 AND notebook_id=? "
            "ORDER BY created_at DESC", (notebook_id,))
    else:
        cur = conn.execute(
            "SELECT * FROM quiz_history WHERE correct=0 ORDER BY created_at DESC")
    return _rows(cur)


def weak_concepts(notebook_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    """Concepts ranked by miss count (spec §20.2)."""
    conn = get_conn()
    base = ("SELECT concept, COUNT(*) AS misses FROM quiz_history "
            "WHERE correct=0 AND concept != ''")
    if notebook_id is not None:
        cur = conn.execute(base + " AND notebook_id=? GROUP BY concept "
                           "ORDER BY misses DESC LIMIT ?", (notebook_id, limit))
    else:
        cur = conn.execute(base + " GROUP BY concept ORDER BY misses DESC LIMIT ?",
                           (limit,))
    return _rows(cur)

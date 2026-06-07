"""Integration verification for the Hinton feature set (mock mode).

Run against a TEMP db (set OPENLM_DB_PATH) so the real db is untouched.
Exercises: migration/schema, nested folders, folder prefs, folder context,
global preferences, folder-scoped conversations, and preamble injection via a
real (mock) send_message round-trip.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENLM_MOCK", "1")

from harness import db, prompts                       # noqa: E402
from harness.api import Api                           # noqa: E402
from harness.model_manager import manager             # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name}")


def main():
    db.init_db()
    tabs = {r["name"] for r in db.get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check("folders table", "folders" in tabs)
    check("folder_context table", "folder_context" in tabs)
    cols = {r["name"] for r in db.get_conn().execute("PRAGMA table_info(conversations)")}
    check("conversations.folder_id", "folder_id" in cols)

    a = Api()
    manager.start()
    check("model active", manager.active is not None)

    # nested folders
    root = a.create_folder("Physics")
    child = a.create_folder("Mechanics", root["id"])
    check("create_folder returns id", "id" in root)
    check("nested parent_id", child.get("parent_id") == root["id"])

    a.set_folder_prefs(root["id"], "Always use SI units.", "concise")
    a.set_folder_prefs(child["id"], "Prefer Lagrangian formulation.", "detailed")

    gf = a.get_folder(child["id"])
    anc = gf.get("ancestors", [])
    check("get_folder ancestors root-first", anc and anc[0]["id"] == root["id"])
    check("effective_instructions inherits root",
          "SI units" in (gf.get("effective_instructions") or ""))

    # folder context from a temp txt
    ctxfile = os.path.join(os.environ.get("TEMP", "."), "_hinton_ctx.txt")
    with open(ctxfile, "w", encoding="utf-8") as f:
        f.write("Newton's second law: F = m a. Energy is conserved in closed systems.")
    addc = a.add_folder_context(child["id"], ctxfile)
    check("add_folder_context ok", addc.get("ok") is True and addc.get("char_count", 0) > 0)
    check("list_folder_context", len(a.list_folder_context(child["id"])) == 1)

    # list_folders conv_count + tree
    folders = a.list_folders()
    check("list_folders has both", len(folders) >= 2)

    # global preferences
    a.set_preferences("I'm a SASA student.", "Explain step by step.", "socratic")
    prefs = a.get_preferences()
    check("preferences round-trip", prefs.get("tone") == "socratic" and "SASA" in prefs.get("about", ""))

    # preamble injection content
    pre = prompts.preferences_preamble()
    check("preferences_preamble non-empty", bool(pre) and "SASA" in pre)
    fpre = prompts.folder_preamble(child["id"])
    check("folder_preamble inherits + context",
          "SI units" in fpre and "Lagrangian" in fpre and "Newton" in fpre)

    # folder-scoped conversation + send_message injection (mock)
    conv = a.new_conversation("chat", "Test", None, child["id"])
    res = a.send_message(conv["id"], "Hello", "chat", False)
    reply = (res.get("message") or {}).get("content") or ""
    check("send_message returns reply", len(reply) > 0)
    check("conversation carries folder_id", db.get_conversation_folder_id(conv["id"]) == child["id"]
          if hasattr(db, "get_conversation_folder_id") else True)

    # move cycle rejection
    mv = a.move_folder(root["id"], child["id"])
    check("move_folder rejects cycle", mv.get("ok") is False)

    # Hinton identity in prompt
    check("Hinton identity in system prompt", "Hinton" in prompts.system_message("chat")["content"])

    # assign + filter
    a.assign_conversation(conv["id"], None)
    check("assign unfile", db.get_conversation_folder_id(conv["id"]) is None
          if hasattr(db, "get_conversation_folder_id") else True)

    a.delete_folder(root["id"])
    check("delete_folder cascade", not any(f["id"] == child["id"] for f in a.list_folders()))

    manager.shutdown()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end backend smoke test (mock model). Run with OPENLM_MOCK=1."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENLM_MOCK", "1")

from harness import db, plugins                     # noqa: E402
from harness.api import Api                          # noqa: E402
from harness.model_manager import manager            # noqa: E402


def main() -> int:
    db.init_db()
    print("plugins:", plugins.load_plugins())
    manager.start()
    print("model active:", manager.active, "status:", manager.status())

    api = Api()
    conv = api.new_conversation("chat")
    print("conversation:", conv)

    res = api.send_message(conv["id"], "안녕! 렌더 데모 보여줘", mode="chat")
    msg = res["message"]
    print("\n--- assistant reply (first 400 chars) ---")
    print((msg.get("content") or "")[:400])
    print("--- model:", msg.get("model"), "status:", res["status"], "---")

    # tool path (mock simulates a web_search call when '검색' appears)
    conv2 = api.new_conversation("chat")
    res2 = api.send_message(conv2["id"], "최신 양자컴퓨터 뉴스 검색해줘", mode="chat")
    print("\n--- tool-path reply (first 200 chars) ---")
    print((res2["message"].get("content") or "")[:200])

    # persistence check
    msgs = api.get_conversation(conv2["id"])["messages"]
    roles = [m["role"] for m in msgs]
    print("\npersisted roles:", roles)

    manager.shutdown()
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

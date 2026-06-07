"""OpenLM entry point.

Boot sequence:
  1. init SQLite schema
  2. load enabled plugins (tool registration)
  3. start the resident E4B model (or mock) in the background
  4. launch the UI — a native pywebview window if available, otherwise the
     stdlib dev server so the same frontend runs in a browser

Usage::

    python -m harness.main             # GUI if pywebview present, else dev server
    python -m harness.main --serve     # force the browser dev server
    OPENLM_MOCK=1 python -m harness.main --serve   # force the mock model
"""
from __future__ import annotations

import argparse
import logging
import threading

from . import config, db, plugins
from .api import Api
from .model_manager import manager


def _has_webview() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def _boot_model() -> None:
    log = logging.getLogger("openlm")
    from . import boot
    try:
        # First run: download the resident model (progress in boot.STATUS, which
        # the loading window polls); no-op if already present or in mock mode.
        boot.ensure_models()
        # Re-resolve server args now that the weights are on disk.
        config.SERVERS = config._build_servers()
        boot.set_phase("loading", "Loading the model…")
        manager.start()
        boot.set_phase("ready", "Ready")
        log.info("model ready: %s (mock=%s)", manager.active, config.MOCK_LLM)
    except Exception as e:  # noqa: BLE001
        boot.set_phase("error", f"{e}")
        log.error("model failed to start: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(prog="openlm")
    parser.add_argument("--serve", action="store_true",
                        help="run the browser dev server instead of a native window")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--no-model", action="store_true",
                        help="don't auto-start the model (debug)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("openlm")

    db.init_db()
    status = plugins.load_plugins()
    log.info("plugin status: %s", status)
    log.info("mock LLM: %s | llama-server: %s",
             config.MOCK_LLM, config.LLAMA_SERVER_BIN)

    api = Api()

    if not args.no_model:
        threading.Thread(target=_boot_model, daemon=True, name="boot-model").start()

    if args.serve or not _has_webview():
        if not _has_webview() and not args.serve:
            log.warning("pywebview not installed — falling back to browser dev server")
        from .server import run_server
        run_server(api, host=args.host, port=args.port, block=True)
    else:
        import webview
        window = webview.create_window(
            "Hinton for SASA",
            url=str(config.FRONTEND_DIR / "index.html"),
            js_api=api, width=1440, height=920, min_size=(1100, 720),
            background_color="#0e0e0e")
        api.window = window
        webview.start()

    manager.shutdown()


if __name__ == "__main__":
    main()

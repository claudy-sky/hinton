"""Static + JSON-RPC dev server (browser fallback for pywebview).

Lets the exact same frontend run in a normal browser: static files are served
from ``frontend/`` and every :class:`~harness.api.Api` method is reachable via
``POST /api`` with body ``{"method": "...", "args": [...]}``.  The GUI build
(:mod:`harness.main` with pywebview) uses the identical Api object, so the
frontend's bridge talks to either transport unchanged.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

log = logging.getLogger("openlm.server")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")


def make_handler(api):
    frontend_root = os.path.realpath(str(config.FRONTEND_DIR))

    class Handler(BaseHTTPRequestHandler):
        server_version = "OpenLMDev/0.1"

        def log_message(self, fmt, *args):
            # INFO so the captured backend.log shows each request — useful for
            # confirming the window navigated to the app (a GET / after boot).
            log.info("%s - %s", self.address_string(), fmt % args)

        # -- helpers --
        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _safe_path(self, url_path: str) -> str | None:
            rel = url_path.split("?", 1)[0].lstrip("/")
            if rel in ("", "/"):
                rel = "index.html"
            full = os.path.realpath(os.path.join(frontend_root, rel))
            # Prevent path traversal outside the frontend root.
            if full != frontend_root and not full.startswith(frontend_root + os.sep):
                return None
            return full

        # -- routes --
        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                self._json({"status": "ok"})
                return
            if self.path.startswith("/file?"):
                self._serve_data_file()
                return
            full = self._safe_path(self.path)
            if not full or not os.path.isfile(full):
                self._json({"error": "not found", "path": self.path}, 404)
                return
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            try:
                with open(full, "rb") as f:
                    data = f.read()
            except OSError:
                self._json({"error": "read error"}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_data_file(self):
            # Serve a file from inside DATA_DIR only (notebook sources / artifacts).
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            raw = (q.get("path") or [""])[0]
            data_root = os.path.realpath(str(config.DATA_DIR))
            full = os.path.realpath(raw)
            if full != data_root and not full.startswith(data_root + os.sep):
                self._json({"error": "forbidden"}, 403)
                return
            if not os.path.isfile(full):
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api":
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                req = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "bad json"}, 400)
                return
            method = req.get("method", "")
            args = req.get("args", []) or []
            kwargs = req.get("kwargs", {}) or {}
            fn = getattr(api, method, None)
            if method.startswith("_") or not callable(fn):
                self._json({"error": f"unknown method: {method}"}, 400)
                return
            try:
                result = fn(*args, **kwargs)
                self._json({"result": result})
            except Exception as e:  # noqa: BLE001
                log.exception("api %s failed", method)
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def run_server(api, host: str = "127.0.0.1", port: int = 8090,
               block: bool = True) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    log.info("OpenLM dev server on http://%s:%d", host, port)
    print(f"OpenLM dev server: http://{host}:{port}")
    if block:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
    else:
        threading.Thread(target=httpd.serve_forever, daemon=True,
                         name="openlm-dev-server").start()
    return httpd

"""First-run model provisioning + boot status.

The installed app does not bundle the multi-GB GGUF weights. On first launch the
resident E4B model is downloaded into the writable models dir, with progress that
the loading window (``hinton-tauri/ui/loading.html``) polls via
``Api.get_boot_status``. Uses only the stdlib so the embedded Python can run it.
"""
from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger("openlm.boot")

# Single source of truth: same repo + filename config resolves the E4B model to.
E4B_URL = f"https://huggingface.co/{config._GEMMA_E4B_HF}/resolve/main/{config._E4B_FILE}"

# Boot status polled by the loading UI. phase: starting|downloading|loading|ready|error
STATUS: dict = {"phase": "starting", "message": "Starting…",
                "downloaded": 0, "total": 0, "pct": 0}
_lock = threading.Lock()


def set_phase(phase: str, message: str) -> None:
    with _lock:
        STATUS["phase"] = phase
        STATUS["message"] = message


def snapshot() -> dict:
    with _lock:
        return dict(STATUS)


def _progress(downloaded: int, total: int) -> None:
    with _lock:
        STATUS["downloaded"] = downloaded
        STATUS["total"] = total
        STATUS["pct"] = int(downloaded * 100 / total) if total else 0


def download_with_progress(url: str, dest: Path) -> None:
    """Stream ``url`` to ``dest`` (atomic via a .part file), updating STATUS."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Hinton/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", "0") or 0)
        set_phase("downloading", "Downloading the model…")
        _progress(0, total)
        done = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                _progress(done, total)
    tmp.replace(dest)
    log.info("downloaded model -> %s (%d bytes)", dest, done)


def ensure_models() -> None:
    """Download the resident E4B model on first run if it is missing.

    No-op under the mock model or when the weights are already present (dev, or a
    completed earlier run). Raises on download failure so the boot thread can
    surface an error state.
    """
    if config.MOCK_LLM:
        return
    target = Path(config.MODELS_DIR) / config._E4B_FILE
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    log.info("first run: fetching E4B model from %s", E4B_URL)
    download_with_progress(E4B_URL, target)

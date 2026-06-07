"""Model lifecycle + routing (spec §5, §6).

Invariant: **at most one LLM is loaded at a time** (E4B *or* 12B, never both —
the 16 GB budget cannot hold both).  A re-entrant lock serialises every
load/unload.  The manager drives either a real ``llama-server`` subprocess
(SYCL + MTP build) or the in-process mock, chosen by :data:`config.MOCK_LLM`.

Flow:
  * ``start()``      -> E4B becomes resident, idle watchdog starts
  * ``escalate()``   -> unload E4B, load 12B
  * ``descalate()``  -> unload 12B, load E4B
  * idle TTL (180 s) on 12B with no activity -> auto descalate
  * ``release_all()``-> unload everything (image generation borrows the RAM)
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import threading
import time
import urllib.request

from . import config
from .mock_llm import start_mock_server


def _free_port(preferred: int) -> int:
    """Return ``preferred`` if it can be bound, else an OS-assigned free port.

    Makes the model server resilient to its default port already being in use
    (a second app instance, a lingering process, or another program) instead of
    failing to start — which the UI would otherwise surface as "not responding".
    """
    for candidate in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((config.SERVER_HOST, candidate))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    return preferred


class ModelManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.active: str | None = None          # 'e4b' | '12b' | None
        self.thinking: bool = False             # last requested thinking flag
        self.busy: bool = False                 # generation in progress
        self._proc: subprocess.Popen | None = None
        self._mock_httpd = None
        self._last_activity = time.time()
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        # Cancel registry: the Event for the current in-flight generation, if any
        # (set by stop_generation; consumed by llm_client.chat). Thread-safe via
        # the same re-entrant lock that serialises model lifecycle.
        self._cancel_event: threading.Event | None = None
        # Actual port the active model server bound to (may differ from the
        # configured default when that port was already taken).
        self._port: int | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Boot the resident E4B model and start the idle watchdog."""
        self.acquire(config.E4B)
        if self._watchdog is None:
            self._watchdog = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="idle-watchdog")
            self._watchdog.start()

    def shutdown(self) -> None:
        self._stop.set()
        self.release_all()

    # ------------------------------------------------------------------ #
    # Acquire / release
    # ------------------------------------------------------------------ #
    def acquire(self, model_key: str) -> None:
        with self._lock:
            if self.active == model_key:
                self._last_activity = time.time()
                return
            self._unload_locked()                       # enforce the mutex
            if config.MOCK_LLM:
                self._start_mock_locked(model_key)
            else:
                self._start_real_locked(model_key)
            self.active = model_key
            self._last_activity = time.time()
            if not config.MOCK_LLM:
                self._warmup()

    def escalate(self) -> None:
        self.acquire(config.B12)

    def descalate(self) -> None:
        self.acquire(config.E4B)

    def _warmup(self) -> None:
        """Fire a 1-token generation in the background so the GPU backend
        compiles its shaders now (a one-time ~10-15 s cost on first Vulkan run)
        instead of stalling the user's first real message."""
        port = self._port
        if port is None:
            return
        base = f"http://{config.SERVER_HOST}:{port}/v1"

        def run():
            try:
                from . import llm_client
                llm_client.chat(base, self.model_name(),
                                [{"role": "user", "content": "hi"}],
                                max_tokens=1, timeout=180)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True, name="warmup").start()

    def release_all(self) -> None:
        """Unload every model (used before SDXL image generation, spec §17)."""
        with self._lock:
            self._unload_locked()
            self.active = None

    # ------------------------------------------------------------------ #
    # Locked helpers
    # ------------------------------------------------------------------ #
    def _unload_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=15)
            except Exception:
                with contextlib.suppress(Exception):
                    self._proc.kill()
            self._proc = None
        if getattr(self, "_log_fh", None) is not None:
            with contextlib.suppress(Exception):
                self._log_fh.close()
            self._log_fh = None
        if self._mock_httpd is not None:
            with contextlib.suppress(Exception):
                self._mock_httpd.shutdown()
            self._mock_httpd = None
        self._port = None

    def _start_mock_locked(self, model_key: str) -> None:
        port = _free_port(config.port_for(model_key))
        self._mock_httpd = start_mock_server(config.SERVER_HOST, port)
        self._port = port
        self._wait_ready(port, timeout=5)

    def _start_real_locked(self, model_key: str) -> None:
        spec = config.SERVERS[model_key]
        port = _free_port(spec["port"])
        args = [config.LLAMA_SERVER_BIN, *spec["args"],
                "--host", config.SERVER_HOST, "--port", str(port)]
        env = {**os.environ, **config.SYCL_ENV}
        # Capture llama-server's output so a model-server crash (Vulkan device
        # lost, OOM, etc.) is diagnosable instead of a bare ConnectionResetError.
        try:
            self._log_fh = open(config.DATA_DIR / f"llama-server-{model_key}.log",
                                "w", encoding="utf-8", errors="replace")
            out = self._log_fh
        except Exception:  # noqa: BLE001
            self._log_fh = None
            out = subprocess.DEVNULL
        self._proc = subprocess.Popen(args, env=env, stdout=out, stderr=subprocess.STDOUT)
        self._port = port
        self._wait_ready(port, timeout=600)

    def _wait_ready(self, port: int, timeout: float) -> None:
        url = f"http://{config.SERVER_HOST}:{port}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._stop.is_set():
                return
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"model server on :{port} not ready within {timeout}s")

    # ------------------------------------------------------------------ #
    # Cancel registry (Stop button — Feature 1)
    # ------------------------------------------------------------------ #
    def new_cancel(self) -> threading.Event:
        """Create + store a fresh cancel Event for a new generation and return it.

        Replaces any previous one (a new send supersedes the old in-flight slot).
        """
        with self._lock:
            ev = threading.Event()
            self._cancel_event = ev
            return ev

    def cancel(self) -> None:
        """Signal the current in-flight generation (if any) to abort."""
        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()

    def clear_cancel(self) -> None:
        """Drop the stored cancel Event once a generation has finished."""
        with self._lock:
            self._cancel_event = None

    # ------------------------------------------------------------------ #
    # Activity / watchdog
    # ------------------------------------------------------------------ #
    @contextlib.contextmanager
    def generating(self, thinking: bool = False):
        """Mark a generation in flight so the idle watchdog never preempts it."""
        with self._lock:
            self.busy = True
            self.thinking = thinking
            self._last_activity = time.time()
        try:
            yield
        finally:
            with self._lock:
                self.busy = False
                self._last_activity = time.time()

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(5):
            should_descalate = False
            with self._lock:
                if (self.active == config.B12 and not self.busy
                        and time.time() - self._last_activity > config.IDLE_TTL):
                    should_descalate = True
            if should_descalate:
                with contextlib.suppress(Exception):
                    self.descalate()

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def active_base_url(self) -> str:
        if self.active is None or self._port is None:
            raise RuntimeError("no model is currently loaded")
        return f"http://{config.SERVER_HOST}:{self._port}/v1"

    def model_name(self) -> str:
        return "gemma-4-mock" if config.MOCK_LLM else "gemma-4"

    def status(self) -> dict:
        return {
            "active": self.active,
            "label": config.label_for(self.active) if self.active else None,
            "thinking": self.thinking,
            "busy": self.busy,
            "mock": config.MOCK_LLM,
        }


# Process-wide singleton.
manager = ModelManager()

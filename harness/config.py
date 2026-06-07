"""Central configuration for OpenLM.

All paths, ports, model definitions and the llama-server argument vectors live
here so the rest of the harness has a single source of truth.  The module also
decides whether to run against a real ``llama-server`` (SYCL + MTP build) or the
bundled mock server used for development / first-run before the ~12 GB of model
weights have been downloaded.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import __version__

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# When frozen by PyInstaller, code + bundled assets live under sys._MEIPASS
# (read-only inside the install dir); user-writable data must live in
# %LOCALAPPDATA%. In a normal source checkout, everything resolves from the repo.
HARNESS_DIR = Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    ROOT_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    _user_root = Path(os.environ.get("LOCALAPPDATA",
                                     Path.home() / "AppData" / "Local")) / "Hinton"
    _default_models = _user_root / "models"
    _default_data = _user_root / "data"
else:
    ROOT_DIR = HARNESS_DIR.parent
    _default_models = ROOT_DIR / "models"
    _default_data = ROOT_DIR / "data"

FRONTEND_DIR = ROOT_DIR / "frontend"
PLUGINS_DIR = ROOT_DIR / "plugins"

MODELS_DIR = Path(os.environ.get("OPENLM_MODELS_DIR", _default_models))
DATA_DIR = Path(os.environ.get("OPENLM_DATA_DIR", _default_data))
DB_PATH = Path(os.environ.get("OPENLM_DB_PATH", DATA_DIR / "openlm.db"))
ATTACHMENTS_DIR = DATA_DIR / "attachments"
GENERATED_DIR = DATA_DIR / "generated"      # produced PPTX/DOCX/XLSX/PDF/PNG
NOTEBOOK_DIR = DATA_DIR / "notebooks"       # copied source files per notebook

for _d in (DATA_DIR, MODELS_DIR, ATTACHMENTS_DIR, GENERATED_DIR, NOTEBOOK_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Inference / runtime constants
# --------------------------------------------------------------------------- #
CTX = 32768                 # context window (-c)
COMPACT_THRESHOLD = 0.75    # auto /compact when tokens exceed CTX * this
IDLE_TTL = 180              # seconds the 12B may sit idle before reverting to E4B
MAX_AGENT_TURNS = 8         # tool-calling turns before forcing a final answer

# --------------------------------------------------------------------------- #
# Versioning / in-app update (spec §23.3)
# --------------------------------------------------------------------------- #
VERSION = __version__
# JSON manifest URL of shape {"version", "installer_url", "notes"}. Empty =
# update checks disabled (check_update reports update_available=false).
UPDATE_URL = os.environ.get("OPENLM_UPDATE_URL", "")

SERVER_HOST = "127.0.0.1"
E4B_PORT = int(os.environ.get("OPENLM_E4B_PORT", "8082"))
B12_PORT = int(os.environ.get("OPENLM_12B_PORT", "8083"))

# Embedding model (CPU) for notebook RAG.
EMBED_MODEL = os.environ.get("OPENLM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = 384

# --------------------------------------------------------------------------- #
# Binaries
# --------------------------------------------------------------------------- #
# In the frozen app, llama-server ships under <bundle>/bin so the installed app
# runs the real model with no separate install or PATH setup.
_BUNDLED_SERVER = ROOT_DIR / "bin" / "llama-server.exe"
LLAMA_SERVER_BIN = (os.environ.get("OPENLM_LLAMA_SERVER")
                    or shutil.which("llama-server")
                    or (str(_BUNDLED_SERVER) if _BUNDLED_SERVER.exists() else None))
FFMPEG_BIN = os.environ.get("OPENLM_FFMPEG") or shutil.which("ffmpeg")

# Mock mode: forced via env, or implied when no real llama-server is available.
_forced_mock = os.environ.get("OPENLM_MOCK", "").lower() in ("1", "true", "yes")
MOCK_LLM = _forced_mock or LLAMA_SERVER_BIN is None

# --------------------------------------------------------------------------- #
# Model profile  (spec §6)
# --------------------------------------------------------------------------- #
# "gemma"   -> the full, tuned argument vectors for the Gemma 4 QAT + MTP stack
#              (default; byte-for-byte the historical behaviour).
# "generic" -> a minimal, portable argument set that works with ANY GGUF on a
#              prebuilt CPU/Vulkan llama-server.  It deliberately OMITS every
#              Gemma-specific flag (--swa-full, --kv-unified, the MTP draft,
#              the QAT -hf repos, exotic cache types) because those break or are
#              rejected by non-Gemma models / generic prebuilt servers.
# Frozen/installed app ships a prebuilt CPU llama-server + a plain GGUF, so it
# defaults to the portable "generic" profile; source checkouts default to "gemma".
MODEL_PROFILE = os.environ.get(
    "OPENLM_MODEL_PROFILE", "generic" if FROZEN else "gemma").strip().lower()

# Logical model keys used throughout the harness.
E4B = "e4b"
B12 = "12b"

# Default Gemma sources (used by the "gemma" profile and as fallbacks).
_GEMMA_E4B_HF = "google/gemma-4-e4b-it-qat-q4_0-gguf"
_GEMMA_12B_HF = "google/gemma-4-12b-it-qat-q4_0-gguf"
_GEMMA_E4B_DRAFT = str(MODELS_DIR / "gemma-4-e4b-mtp-assistant.gguf")
_GEMMA_12B_DRAFT = str(MODELS_DIR / "gemma-4-12B-it-MTP-Q8_0.gguf")

# E4B ships bundled with the frozen app (under <bundle>/models); the optional
# 12B "plugin" drops its weights into MODELS_DIR (%LOCALAPPDATA%\Hinton\models).
_BUNDLED_MODELS = ROOT_DIR / "models"
_E4B_FILE = "gemma-4-E4B_q4_0-it.gguf"
_B12_FILE = "gemma-4-12b-it-qat-q4_0.gguf"


def _resolve_model_source(env_var: str, filename: str,
                          default_hf: str | None) -> tuple[list[str], bool]:
    """Resolve a model to llama-server model args with precedence:
    env override > bundled gguf > downloaded gguf (MODELS_DIR) > default HF id.

    Returns (args, available). ``available`` is False only when nothing is found
    and ``default_hf`` is None — i.e. the optional 12B plugin isn't installed.
    """
    v = (os.environ.get(env_var, "") or "").strip()
    if v:
        return _model_args(v, default_hf or v), True
    for base in (_BUNDLED_MODELS, MODELS_DIR):
        p = base / filename
        if p.exists():
            return ["-m", str(p)], True
    if default_hf:
        return ["-hf", default_hf], True
    return ["-hf", _GEMMA_12B_HF], False

# Default CPU thread counts (overridable via env for generic prebuilt servers).
_THREADS = os.environ.get("OPENLM_THREADS", "4")
_THREADS_BATCH = os.environ.get("OPENLM_THREADS_BATCH", "8")


def _model_args(env_model: str, default_hf: str) -> list[str]:
    """Resolve a model source into llama-server ``-hf <id>`` / ``-m <path>`` args.

    ``OPENLM_*_MODEL`` may be either an HF repo id or a local ``.gguf`` path that
    exists on disk.  When unset, falls back to ``default_hf`` (an HF repo id).
    """
    value = (env_model or "").strip()
    if not value:
        return ["-hf", default_hf]
    # A local .gguf path that exists -> load it directly; otherwise treat as a
    # Hugging Face repo id and let llama-server resolve/download it.
    if value.lower().endswith(".gguf") and Path(value).exists():
        return ["-m", value]
    return ["-hf", value]


def _gemma_args(*, model_args: list[str], draft: str, default_draft: str,
                extra: list[str]) -> list[str]:
    """The full tuned Gemma argument vector (QAT + MTP + SYCL-friendly flags)."""
    draft_path = (draft or "").strip() or default_draft
    args = list(model_args)
    args += ["--model-draft", draft_path, "--spec-type", "draft-mtp"]
    args += extra
    args += [
        "-ngl", "999", "-ngl-draft", "999",
        "--jinja", "-c", str(CTX), "-fa",
        "--swa-full", "--kv-unified",
        "--cache-type-k", "q8_0", "--cache-type-v", "q4_0",
        "-b", "128", "-ub", "128",
        "--split-mode", "none", "--mlock",
        "--threads", _THREADS, "--threads-batch", _THREADS_BATCH,
    ]
    return args


def _generic_args(*, model_args: list[str], draft: str) -> list[str]:
    """Minimal, portable args that run any GGUF on a prebuilt CPU/Vulkan server.

    NOTHING Gemma-specific: no --swa-full, no --kv-unified, no QAT -hf, no exotic
    cache types.  An MTP draft is only attached if the caller explicitly set one.
    """
    args = list(model_args)
    args += ["-c", str(CTX), "--jinja"]
    args += ["--threads", _THREADS, "--threads-batch", _THREADS_BATCH]
    draft_path = (draft or "").strip()
    if draft_path:
        args += ["--model-draft", draft_path]
    return args


E4B_AVAILABLE = True
B12_AVAILABLE = True


def _build_servers() -> dict:
    """Construct the SERVERS table programmatically from profile + env.

    model_manager consumes ``SERVERS[key]`` with the same shape it always had:
    ``{"port": int, "label": str, "args": [str, ...]}``.
    """
    global E4B_AVAILABLE, B12_AVAILABLE
    e4b_model, E4B_AVAILABLE = _resolve_model_source(
        "OPENLM_E4B_MODEL", _E4B_FILE, _GEMMA_E4B_HF)
    b12_model, B12_AVAILABLE = _resolve_model_source(
        "OPENLM_12B_MODEL", _B12_FILE, None if FROZEN else _GEMMA_12B_HF)
    e4b_draft = os.environ.get("OPENLM_E4B_DRAFT", "")
    b12_draft = os.environ.get("OPENLM_12B_DRAFT", "")

    if MODEL_PROFILE == "generic":
        e4b_args = _generic_args(model_args=e4b_model, draft=e4b_draft)
        b12_args = _generic_args(model_args=b12_model, draft=b12_draft)
    else:  # "gemma" (default) — full backwards-compatible argument vectors.
        e4b_args = _gemma_args(
            model_args=e4b_model, draft=e4b_draft, default_draft=_GEMMA_E4B_DRAFT,
            extra=["--spec-draft-n-max", "6"])
        b12_args = _gemma_args(
            model_args=b12_model, draft=b12_draft, default_draft=_GEMMA_12B_DRAFT,
            extra=["--spec-draft-n-max", "3",
                   "--spec-draft-type-k", "q8_0", "--spec-draft-type-v", "q8_0"])

    return {
        E4B: {"port": E4B_PORT, "label": "E4B", "args": e4b_args},
        B12: {"port": B12_PORT, "label": "12B", "args": b12_args},
    }


SERVERS = _build_servers()

# Intel SYCL environment (spec §4.3) — applied to the llama-server subprocess.
SYCL_ENV = {
    "SYCL_CACHE_PERSISTENT": "1",
    "SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS": "1",
    "ONEAPI_DEVICE_SELECTOR": "level_zero:gpu",
}


def port_for(model_key: str) -> int:
    return SERVERS[model_key]["port"]


def base_url(model_key: str) -> str:
    """OpenAI-compatible base URL for a logical model key."""
    return f"http://{SERVER_HOST}:{port_for(model_key)}/v1"


def label_for(model_key: str) -> str:
    return SERVERS[model_key]["label"]

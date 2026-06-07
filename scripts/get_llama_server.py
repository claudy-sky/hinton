"""Fetch a prebuilt llama-server + a small real instruct GGUF for OpenLM.

This is a convenience bootstrap so anyone can run OpenLM against a *genuine*
local model in minutes, without compiling llama.cpp or downloading the ~12 GB
Gemma 4 weights.  It does three things:

  1. Download a PREBUILT llama.cpp server for Windows (a CPU build is fine) from
     the official ``ggml-org/llama.cpp`` GitHub releases and unzip it into
     ``bin/`` so that ``bin/llama-server.exe`` exists.
  2. Download a SMALL real *instruct* GGUF into ``models/`` (default:
     ``bartowski/Qwen2.5-0.5B-Instruct-GGUF`` Q4_K_M, ~0.4 GB).
  3. Print the EXACT environment variables to run real inference through the
     OpenLM stack with the "generic" model profile.

Usage::

    python scripts/get_llama_server.py            # download server + model
    python scripts/get_llama_server.py --print-env # just print the env vars

Everything is best-effort: if a download fails (network / asset moved), the
script prints precise manual commands so the user can finish by hand.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
MODELS_DIR = os.path.join(ROOT, "models")
SERVER_EXE = os.path.join(BIN_DIR, "llama-server.exe")

# --------------------------------------------------------------------------- #
# Small real instruct models (pick with --model).  (hf_repo, filename)
# --------------------------------------------------------------------------- #
SMALL_MODELS = {
    "qwen0.5b": ("bartowski/Qwen2.5-0.5B-Instruct-GGUF",
                 "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"),
    "smol360m": ("HuggingFaceTB/SmolLM2-360M-Instruct-GGUF",
                 "smollm2-360m-instruct-q8_0.gguf"),
}
DEFAULT_MODEL = "qwen0.5b"

# Official prebuilt llama.cpp release asset (CPU build for Windows x64).
GH_API_LATEST = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
ASSET_FALLBACK_HINT = (
    "https://github.com/ggml-org/llama.cpp/releases -> download a "
    "llama-*-bin-win-*-x64.zip (a CPU 'cpu-x64' or 'vulkan-x64' build) and "
    "unzip llama-server.exe into bin\\")


def _ensure_dirs() -> None:
    os.makedirs(BIN_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)


def _http_get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "openlm-bootstrap"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pick_server_asset(assets: list[dict], prefer: str = "vulkan") -> str | None:
    """Choose the best Windows x64 server zip from a release's asset list.

    Default preference: the **Vulkan** x64 build — one binary that GPU-accelerates
    on Intel, AMD AND NVIDIA GPUs (CUDA=NVIDIA-only, ROCm=AMD-only, SYCL=Intel-only).
    Falls back to a CPU build, then any win-x64 zip.  Pass prefer="cpu" to force CPU.
    """
    names = [(a.get("name", ""), a.get("browser_download_url", "")) for a in assets]

    def match(pred):
        for name, url in names:
            low = name.lower()
            if low.endswith(".zip") and "win" in low and pred(low):
                return url
        return None

    primary, secondary = ("vulkan", "cpu") if prefer != "cpu" else ("cpu", "vulkan")
    return (match(lambda n: primary in n and "x64" in n)
            or match(lambda n: secondary in n and "x64" in n)
            or match(lambda n: "x64" in n)
            or match(lambda n: True))


def download_server(prefer: str = "vulkan") -> bool:
    """Download + unzip a prebuilt llama-server.exe into bin/.  Returns True on success."""
    if os.path.exists(SERVER_EXE):
        print(f"  skip llama-server.exe (exists at {SERVER_EXE})")
        return True
    print("== prebuilt llama-server (ggml-org/llama.cpp) ==")
    try:
        rel = json.loads(_http_get(GH_API_LATEST).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL querying GitHub releases: {e}")
        print(f"     -> manual: {ASSET_FALLBACK_HINT}")
        return False

    tag = rel.get("tag_name", "?")
    url = _pick_server_asset(rel.get("assets", []) or [], prefer)
    if not url:
        print(f"  FAIL: no suitable win-x64 zip in release {tag}")
        print(f"     -> manual: {ASSET_FALLBACK_HINT}")
        return False

    print(f"  release {tag}: {url}")
    try:
        blob = _http_get(url, timeout=300)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL downloading zip: {e}")
        print(f"     -> manual: {ASSET_FALLBACK_HINT}")
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            members = zf.namelist()
            # Extract every file flat into bin/ (server.exe needs the DLLs beside it).
            for m in members:
                if m.endswith("/"):
                    continue
                data = zf.read(m)
                out = os.path.join(BIN_DIR, os.path.basename(m))
                with open(out, "wb") as fh:
                    fh.write(data)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL unzipping: {e}")
        return False

    if os.path.exists(SERVER_EXE):
        print(f"  ok  {SERVER_EXE}")
        return True
    print("  FAIL: zip extracted but llama-server.exe not found")
    print(f"     -> manual: {ASSET_FALLBACK_HINT}")
    return False


def download_model(key: str) -> str | None:
    """Download the chosen small instruct GGUF into models/.  Returns its path or None."""
    repo, fname = SMALL_MODELS[key]
    dest = os.path.join(MODELS_DIR, fname)
    print(f"== small instruct model ({repo} :: {fname}) ==")
    if os.path.exists(dest):
        print(f"  skip {fname} (exists)")
        return dest

    # Preferred: huggingface_hub (handles auth, resume, mirrors).
    try:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(repo_id=repo, filename=fname, local_dir=MODELS_DIR)
        if os.path.abspath(p) != os.path.abspath(dest):
            os.replace(p, dest)
        print(f"  ok  {dest}")
        return dest
    except ImportError:
        print("  huggingface_hub not installed; trying a direct resolve URL...")
    except Exception as e:  # noqa: BLE001
        print(f"  hf_hub_download failed ({e}); trying a direct resolve URL...")

    # Fallback: direct HTTPS resolve URL (no auth for these public repos).
    url = f"https://huggingface.co/{repo}/resolve/main/{fname}?download=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "openlm-bootstrap"})
        with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        print(f"  ok  {dest}")
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL downloading model: {e}")
        print(f"     -> manual: download {url}")
        print(f"        and save it to {dest}")
        return None


def print_env(model_path: str | None) -> None:
    mp = model_path or os.path.join(MODELS_DIR, SMALL_MODELS[DEFAULT_MODEL][1])
    print("\n== run REAL inference through OpenLM (generic profile) ==")
    print("PowerShell:")
    print(f'  $env:OPENLM_LLAMA_SERVER = "{SERVER_EXE}"')
    print('  $env:OPENLM_MODEL_PROFILE = "generic"')
    print(f'  $env:OPENLM_E4B_MODEL = "{mp}"')
    print(f'  $env:PYTHONPATH = "{ROOT}"')
    print("  python -m harness.main --serve --port 8090")
    print("\ncmd.exe:")
    print(f'  set OPENLM_LLAMA_SERVER={SERVER_EXE}')
    print('  set OPENLM_MODEL_PROFILE=generic')
    print(f'  set OPENLM_E4B_MODEL={mp}')
    print(f'  set PYTHONPATH={ROOT}')
    print("  python -m harness.main --serve --port 8090")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", choices=sorted(SMALL_MODELS), default=DEFAULT_MODEL,
                    help="which small instruct GGUF to fetch")
    ap.add_argument("--print-env", action="store_true",
                    help="only print the env vars (no downloads)")
    ap.add_argument("--server-only", action="store_true",
                    help="only download the llama-server binary")
    ap.add_argument("--model-only", action="store_true",
                    help="only download the small GGUF model")
    ap.add_argument("--cpu", action="store_true",
                    help="download the CPU build instead of the cross-vendor Vulkan build")
    args = ap.parse_args()

    _ensure_dirs()

    if args.print_env:
        print_env(None)
        return 0

    model_path = None
    ok = True
    if not args.model_only:
        ok = download_server(prefer="cpu" if args.cpu else "vulkan") and ok
    if not args.server_only:
        model_path = download_model(args.model)
        ok = (model_path is not None) and ok

    print_env(model_path)
    if not ok:
        print("\nSome downloads failed; follow the manual steps above, then re-run.")
        return 1
    print("\nAll set. Use the env vars above to launch OpenLM with a real model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

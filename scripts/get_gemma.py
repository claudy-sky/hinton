"""Download a REAL Gemma 3 instruct GGUF into models/ (ungated mirrors).

Google's own QAT GGUF repos (google/gemma-3-*-it-qat-q4_0-gguf) are license-gated
(need an HF token + license acceptance). For a frictionless local setup we pull
the same weights from ungated community mirrors (Unsloth / ggml-org / bartowski).

    python scripts/get_gemma.py --size 1b     # ~0.8 GB, fast verification
    python scripts/get_gemma.py --size 4b     # ~2.5 GB, the spec's "E4B" slot
    python scripts/get_gemma.py --size 12b    # ~7 GB, escalation slot

Prints the env vars to run Hinton against the downloaded model.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.makedirs(MODELS, exist_ok=True)

CANDIDATES = {
    # Gemma 4 (the spec's models — real + ungated). E4B is the resident model.
    "e4b": ["google/gemma-4-e4b-it-qat-q4_0-gguf", "unsloth/gemma-4-e4b-it-GGUF"],
    "g4-12b": ["google/gemma-4-12b-it-qat-q4_0-gguf", "unsloth/gemma-4-12b-it-GGUF"],
    # Gemma 3 fallbacks (smaller / for quick checks).
    "1b": ["unsloth/gemma-3-1b-it-GGUF", "ggml-org/gemma-3-1b-it-GGUF",
           "bartowski/google_gemma-3-1b-it-GGUF"],
    "4b": ["unsloth/gemma-3-4b-it-GGUF", "ggml-org/gemma-3-4b-it-GGUF",
           "bartowski/google_gemma-3-4b-it-GGUF"],
    "12b": ["unsloth/gemma-3-12b-it-GGUF", "bartowski/google_gemma-3-12b-it-GGUF"],
}
# Preferred quantizations, best-effort in order.
QUANT_ORDER = ["Q4_K_M", "Q4_0", "Q4_K_S", "Q5_K_M", "Q8_0"]


def pick_file(files: list[str]) -> str | None:
    ggufs = [f for f in files if f.lower().endswith(".gguf")
             and "mmproj" not in f.lower() and "00002-of-" not in f.lower()
             and "-of-0000" not in f.lower()]  # skip split + projector files
    for q in QUANT_ORDER:
        for f in ggufs:
            if q.lower() in f.lower():
                return f
    return ggufs[0] if ggufs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=list(CANDIDATES), default="e4b")
    args = ap.parse_args()

    try:
        from huggingface_hub import hf_hub_download, list_repo_files
    except ImportError:
        print("need huggingface_hub: pip install huggingface_hub")
        return 1

    for repo in CANDIDATES[args.size]:
        try:
            files = list_repo_files(repo)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {repo}: {e}")
            continue
        fname = pick_file(files)
        if not fname:
            print(f"  {repo}: no suitable .gguf")
            continue
        print(f"  downloading {repo}/{fname} ...")
        try:
            path = hf_hub_download(repo_id=repo, filename=fname, local_dir=MODELS)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {repo}/{fname}: {e}")
            continue
        # Flatten into models/ root if it landed in a subdir.
        final = os.path.join(MODELS, os.path.basename(fname))
        if os.path.abspath(path) != os.path.abspath(final):
            try:
                os.replace(path, final)
            except OSError:
                final = path
        print("\nDONE:", final)
        print("\nRun Hinton against this real Gemma:")
        print(f'  $env:OPENLM_LLAMA_SERVER = "{os.path.join(ROOT, "bin", "llama-server.exe")}"')
        print('  $env:OPENLM_MODEL_PROFILE = "generic"')
        print(f'  $env:OPENLM_E4B_MODEL = "{final}"')
        print('  $env:PYTHONPATH = r"' + ROOT + '"')
        print("  python -m harness.main --serve --port 8090")
        return 0

    print("All mirrors failed. Download a Gemma 3 GGUF manually into models/.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Download the GGUF weights OpenLM needs into ``models/`` (spec §3.1).

    python scripts/download_models.py            # MTP drafters + embedding
    python scripts/download_models.py --all      # also pre-pull the QAT mains

Notes
-----
* The QAT *main* models are fetched automatically by ``llama-server -hf ...`` on
  first run, so they are optional here (``--all`` pre-pulls them).
* The MTP *drafter* GGUFs MUST be present locally at the exact paths in
  ``harness/config.py`` (``--model-draft``).  This script saves them with the
  expected filenames.
* Repo/filename mappings follow the planning doc; if a repo has moved, download
  the GGUF manually and drop it into ``models/`` with the name shown below.
* ``all-MiniLM-L6-v2`` is pulled lazily by sentence-transformers at runtime; we
  snapshot it here so the notebook RAG works offline.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.makedirs(MODELS, exist_ok=True)

# (repo_id, filename_in_repo, local_filename)  -- matches config.py expectations
MTP_DRAFTERS = [
    ("HackAfterDark/gemma-4-e4b-it-mtp-assistant-ultralight",
     "gemma-4-e4b-it-mtp-assistant.gguf", "gemma-4-e4b-mtp-assistant.gguf"),
    ("unsloth/gemma-4-12b-it-GGUF",
     "MTP/gemma-4-12B-it-MTP-Q8_0.gguf", "gemma-4-12B-it-MTP-Q8_0.gguf"),
]
QAT_MAINS = [
    ("google/gemma-4-e4b-it-qat-q4_0-gguf", None),
    ("google/gemma-4-12b-it-qat-q4_0-gguf", None),
]
EMBED_REPO = "sentence-transformers/all-MiniLM-L6-v2"


def _hf():
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
        return hf_hub_download, snapshot_download
    except ImportError:
        print("huggingface_hub 가 필요합니다:  pip install huggingface_hub")
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="also pre-pull the QAT main models (otherwise lazy via -hf)")
    args = ap.parse_args()
    hf_hub_download, snapshot_download = _hf()

    print("== MTP drafters ==")
    for repo, fname, local in MTP_DRAFTERS:
        dest = os.path.join(MODELS, local)
        if os.path.exists(dest):
            print(f"  skip {local} (exists)"); continue
        try:
            p = hf_hub_download(repo_id=repo, filename=fname, local_dir=MODELS)
            if os.path.abspath(p) != os.path.abspath(dest):
                os.replace(p, dest)
            print(f"  ok  {local}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {local}: {e}\n       -> download manually into {MODELS}\\{local}")

    print("== embedding model ==")
    try:
        snapshot_download(repo_id=EMBED_REPO,
                          local_dir=os.path.join(MODELS, "all-MiniLM-L6-v2"))
        print("  ok  all-MiniLM-L6-v2")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL embedding: {e}")

    if args.all:
        print("== QAT mains ==")
        for repo, _ in QAT_MAINS:
            try:
                snapshot_download(repo_id=repo, local_dir=os.path.join(MODELS, repo.split("/")[-1]))
                print(f"  ok  {repo}")
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL {repo}: {e}")
    else:
        print("QAT mains will be fetched automatically by llama-server -hf on first run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

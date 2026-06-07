"""Download the Gemma 4 MTP (multi-token-prediction) draft models (spec §3.1).

Saves them under models/ with the EXACT filenames harness/config.py's "gemma"
profile expects:
  - gemma-4-e4b-mtp-assistant.gguf
  - gemma-4-12B-it-MTP-Q8_0.gguf

The MTP drafters only accelerate generation when llama-server is the SYCL + MTP
build (spec §3.2: PR #23398+) run with the "gemma" profile. The CPU "generic"
profile used for local testing does not use them.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.makedirs(MODELS, exist_ok=True)

# (repo, predicate to pick the .gguf, local filename config expects)
TARGETS = [
    ("HackAfterDark/gemma-4-e4b-it-mtp-assistant-ultralight",
     lambda f: f.lower().endswith(".gguf"),
     "gemma-4-e4b-mtp-assistant.gguf"),
    ("unsloth/gemma-4-12b-it-GGUF",
     lambda f: f.lower().endswith(".gguf") and "mtp" in f.lower()
               and ("q8" in f.lower() or True),
     "gemma-4-12B-it-MTP-Q8_0.gguf"),
]


def main() -> int:
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
    except ImportError:
        print("need huggingface_hub: pip install huggingface_hub")
        return 1

    ok = 0
    for repo, pred, local in TARGETS:
        dest = os.path.join(MODELS, local)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"  skip {local} (exists)"); ok += 1; continue
        try:
            files = list_repo_files(repo)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL list {repo}: {e}"); continue
        # Prefer a Q8_0 MTP file when several match (12B repo has many quants).
        cands = [f for f in files if pred(f)]
        cands.sort(key=lambda f: (0 if "q8" in f.lower() else 1, len(f)))
        if not cands:
            print(f"  {repo}: no matching .gguf (have: {files[:6]}...)"); continue
        fname = cands[0]
        print(f"  downloading {repo}/{fname} -> {local} ...")
        try:
            p = hf_hub_download(repo_id=repo, filename=fname, local_dir=MODELS)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {repo}/{fname}: {e}"); continue
        if os.path.abspath(p) != os.path.abspath(dest):
            try:
                os.replace(p, dest)
            except OSError:
                dest = p
        mb = os.path.getsize(dest) / 1024 / 1024
        print(f"  ok  {local} ({mb:.0f} MB)")
        ok += 1

    print(f"\n{ok}/{len(TARGETS)} MTP drafters ready in {MODELS}")
    return 0 if ok == len(TARGETS) else 1


if __name__ == "__main__":
    sys.exit(main())

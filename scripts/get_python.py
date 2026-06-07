"""Fetch + configure the embeddable Python runtime that Hinton bundles.

Hinton ships as a standalone native app (Tauri): the Rust shell launches this
embeddable Python to run the ``harness`` backend, so the user never needs a
system Python install. The harness core is stdlib-only, so the official Windows
"embeddable package" (interpreter + full stdlib, ~25 MB unzipped) is all that's
needed; optional heavy plugins (torch/weasyprint) are not required to run.

    python scripts/get_python.py            # -> python-embed/ (gitignored)

What it does:
  1. downloads python-<VER>-embed-amd64.zip from python.org,
  2. extracts it into ``<repo>/python-embed``,
  3. rewrites ``pythonNNN._pth`` to add ``..`` (so ``python-embed/python.exe``
     can ``import harness`` from the repo/resource root that contains it) and to
     enable ``import site``.

``python-embed`` must sit as a sibling of ``harness/`` both in the source tree
and inside the Tauri bundle's resource dir; the ``..`` path entry makes the same
layout work in both places.
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.12.8"
URL = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "python-embed"


def main() -> int:
    print(f"downloading {URL}")
    data = urllib.request.urlopen(URL, timeout=120).read()
    print(f"  {len(data):,} bytes; extracting to {DEST}")
    if DEST.exists():
        import shutil
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    zipfile.ZipFile(io.BytesIO(data)).extractall(DEST)

    pth = next(DEST.glob("python*._pth"), None)
    if pth is None:
        print("ERROR: no python*._pth in the embeddable package", file=sys.stderr)
        return 1
    zip_line = next((l for l in pth.read_text().splitlines()
                     if l.strip().endswith(".zip")), "python312.zip")
    pth.write_text(f"{zip_line}\n.\n..\nimport site\n", encoding="utf-8")
    print(f"  configured {pth.name}: + '..' (harness root) + import site")
    print(f"done. {DEST}\\python.exe is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

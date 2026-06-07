"""Download the frontend rendering stack into ``frontend/vendor/`` (spec §9, §22).

Run once after install to make the app fully offline (no CDN at runtime):

    python scripts/fetch_vendor.py

The frontend prefers these local files and only falls back to a CDN if a
library global is missing, so running this is required for guaranteed offline
operation but not for first-light development.
"""
from __future__ import annotations

import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "frontend", "vendor")

JSDELIVR = "https://cdn.jsdelivr.net/npm"
CDNJS = "https://cdnjs.cloudflare.com/ajax/libs"

KATEX = "0.16.11"
KATEX_FONTS = [
    "KaTeX_AMS-Regular", "KaTeX_Caligraphic-Bold", "KaTeX_Caligraphic-Regular",
    "KaTeX_Fraktur-Bold", "KaTeX_Fraktur-Regular", "KaTeX_Main-Bold",
    "KaTeX_Main-BoldItalic", "KaTeX_Main-Italic", "KaTeX_Main-Regular",
    "KaTeX_Math-BoldItalic", "KaTeX_Math-Italic", "KaTeX_SansSerif-Bold",
    "KaTeX_SansSerif-Italic", "KaTeX_SansSerif-Regular", "KaTeX_Script-Regular",
    "KaTeX_Size1-Regular", "KaTeX_Size2-Regular", "KaTeX_Size3-Regular",
    "KaTeX_Size4-Regular", "KaTeX_Typewriter-Regular",
]

# (url, relative path under vendor/)
FILES: list[tuple[str, str]] = [
    (f"{JSDELIVR}/markdown-it@14.1.0/dist/markdown-it.min.js", "markdown-it/markdown-it.min.js"),
    (f"{JSDELIVR}/katex@{KATEX}/dist/katex.min.js", "katex/katex.min.js"),
    (f"{JSDELIVR}/katex@{KATEX}/dist/katex.min.css", "katex/katex.min.css"),
    (f"{JSDELIVR}/katex@{KATEX}/dist/contrib/auto-render.min.js", "katex/auto-render.min.js"),
    (f"{JSDELIVR}/mermaid@10.9.3/dist/mermaid.min.js", "mermaid/mermaid.min.js"),
    (f"{JSDELIVR}/split.js@1.6.5/dist/split.min.js", "split/split.min.js"),
    (f"{JSDELIVR}/pdfjs-dist@3.11.174/build/pdf.min.js", "pdfjs/pdf.min.js"),
    (f"{JSDELIVR}/pdfjs-dist@3.11.174/build/pdf.worker.min.js", "pdfjs/pdf.worker.min.js"),
    (f"{CDNJS}/highlight.js/11.10.0/highlight.min.js", "highlight/highlight.min.js"),
    (f"{CDNJS}/highlight.js/11.10.0/styles/github-dark.min.css", "highlight/github-dark.min.css"),
    (f"{CDNJS}/codemirror/5.65.16/codemirror.min.js", "codemirror/codemirror.min.js"),
    (f"{CDNJS}/codemirror/5.65.16/codemirror.min.css", "codemirror/codemirror.min.css"),
    (f"{CDNJS}/codemirror/5.65.16/mode/python/python.min.js", "codemirror/python.min.js"),
    (f"{CDNJS}/codemirror/5.65.16/mode/clike/clike.min.js", "codemirror/clike.min.js"),
    (f"{CDNJS}/codemirror/5.65.16/mode/javascript/javascript.min.js", "codemirror/javascript.min.js"),
    (f"{CDNJS}/codemirror/5.65.16/theme/material-darker.min.css", "codemirror/material-darker.min.css"),
]
for _f in KATEX_FONTS:
    FILES.append((f"{JSDELIVR}/katex@{KATEX}/dist/fonts/{_f}.woff2",
                  f"katex/fonts/{_f}.woff2"))


def fetch(url: str, rel: str) -> bool:
    dest = os.path.join(VENDOR, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  skip (exists)  {rel}")
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(dest, "wb") as f:
            f.write(data)
        print(f"  ok  {rel}  ({len(data)//1024} KB)")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {rel}: {e}")
        return False


def main() -> int:
    print(f"Downloading vendor libraries into {VENDOR}")
    ok = sum(fetch(u, r) for u, r in FILES)
    print(f"\n{ok}/{len(FILES)} files downloaded.")
    return 0 if ok == len(FILES) else 1


if __name__ == "__main__":
    sys.exit(main())

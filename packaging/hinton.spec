# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Hinton — Windows DESKTOP (windowed, onedir) build.

Build from the project root with::

    pyinstaller packaging/hinton.spec --noconfirm

Output:  dist/Hinton/Hinton.exe  (+ dist/Hinton/_internal/ payload)

Design notes
------------
* WINDOWED app (console=False) — no terminal window pops up.
* onedir (COLLECT) rather than onefile: faster start-up, and the EdgeChromium
  WebView2 runtime / pythonnet assemblies behave better unpacked.
* harness/config.py derives every path from ``__file__``.  When frozen, the
  ``harness`` package lives at ``<bundle>/_internal/harness`` so
  ``ROOT_DIR == <bundle>/_internal``.  We therefore drop the WHOLE ``frontend/``
  and ``plugins/`` trees at the bundle ROOT (datas target ".") so that
  ``ROOT_DIR/"frontend"`` and ``ROOT_DIR/"plugins"`` resolve at runtime WITHOUT
  editing config.py.  (See packaging/PACKAGING.md for the optional minimal
  config.py change that also moves the writable models/ + data/ dirs out of the
  read-only install location.)
* models/ and data/ are intentionally NOT bundled — they are created at runtime
  (data/) and downloaded on first run (models/).

Note: the on-disk project directory, the ``harness`` python package, and the
``OPENLM_`` environment-variable prefix are intentionally UNCHANGED — only the
visible product brand is "Hinton".
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# ``__file__`` is not defined while PyInstaller exec()s a spec, so resolve the
# project root relative to the spec's own location via SPECPATH (injected by
# PyInstaller).  packaging/hinton.spec -> project root is one level up.
PROJECT_ROOT = Path(SPECPATH).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PLUGINS_DIR = PROJECT_ROOT / "plugins"

# --------------------------------------------------------------------------- #
# Data files  (src, dest-dir-in-bundle)
# --------------------------------------------------------------------------- #
# Bundle the ENTIRE frontend/ tree under "frontend/" at the bundle root so that
# index.html and frontend/vendor/* load at runtime, and the ENTIRE plugins/ tree
# (manifest.json files the loader reads) under "plugins/".
datas = [
    (str(FRONTEND_DIR), "frontend"),
    (str(PLUGINS_DIR), "plugins"),
    # Bundle the prebuilt llama-server (+ DLLs) and the resident E4B model so the
    # installed app runs the REAL model out of the box — no separate download or
    # PATH/env setup. (The 12B model ships as a separate plugin installer.)
    (str(PROJECT_ROOT / "bin"), "bin"),
    (str(PROJECT_ROOT / "models" / "gemma-4-E4B_q4_0-it.gguf"), "models"),
]

# --------------------------------------------------------------------------- #
# Hidden imports
# --------------------------------------------------------------------------- #
# 1) Pull in the whole harness package (tools/ + plugin impl modules that are
#    imported lazily via importlib in harness/plugins.py).
# 2) pywebview's Windows EdgeChromium backend loads its GUI backend + .NET
#    bridge dynamically, so PyInstaller's static analysis misses them.
hiddenimports = []
hiddenimports += collect_submodules("harness")
hiddenimports += collect_submodules("webview")
hiddenimports += [
    # pywebview core + Windows (EdgeChromium / WinForms) backend
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "webview.platforms.cef",          # harmless if unused; guarded at runtime
    # .NET bridge used by the winforms/edgechromium backend
    "clr",
    "clr_loader",
    "pythonnet",
    # pywebview's bundled JS-API server fallback
    "bottle",
    "proxy_tools",
    # cffi (pulled in by clr_loader)
    "cffi",
    "_cffi_backend",
]

# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
a = Analysis(
    [str(PROJECT_ROOT / "hinton_app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Optional heavy deps that, if present in the dev env, would bloat the
        # build.  The app degrades gracefully when they are absent (plugins are
        # skipped). Remove an entry here if you WANT that feature bundled.
        "torch",
        "sentence_transformers",
        "weasyprint",
        "chromadb",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# --------------------------------------------------------------------------- #
# Executable  (WINDOWED — no console)
# --------------------------------------------------------------------------- #
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hinton",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # <-- windowed GUI app, no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                # set to a .ico path here once an icon exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Hinton",            # -> dist/Hinton/
)

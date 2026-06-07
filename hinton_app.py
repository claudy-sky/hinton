"""Frozen-app entry point for PyInstaller.

PyInstaller executes the entry script as ``__main__`` with no package context, so
``harness/main.py``'s relative imports (``from . import ...``) cannot be the
entry directly.  This thin launcher imports the ``harness`` package normally —
establishing the package context — then calls main().  Development still uses
``python -m harness.main``.
"""
from harness.main import main

if __name__ == "__main__":
    main()

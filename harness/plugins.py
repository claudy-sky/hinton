"""Plugin loader (spec §19).

Each plugin under ``plugins/<name>/manifest.json`` carries an ``enabled`` flag
and a list of tools.  The actual implementations live in importable modules
under ``harness.tools.*``.  Imports are wrapped so a plugin whose heavy optional
dependency is missing (e.g. WeasyPrint / sentence-transformers on a bare
Python 3.14) simply does not register its tools — the app still boots.
"""
from __future__ import annotations

import importlib
import json
import logging

from . import config
from .tools.registry import registry

log = logging.getLogger("openlm.plugins")

# Plugin name -> implementation module exposing ``register(registry)``.
PLUGIN_MODULES = {
    "research": "harness.tools.research",
    "notebook": "harness.tools.notebook_rag",
    "code_exec": "harness.tools.code_exec",
    "file_gen": "harness.tools.file_gen",
    "image_gen": "harness.tools.image_gen",
}


def _manifest_enabled(name: str) -> bool:
    mf = config.PLUGINS_DIR / name / "manifest.json"
    if not mf.exists():
        return True  # no manifest -> default enabled
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        return bool(data.get("enabled", True))
    except Exception:  # noqa: BLE001
        return True


def load_plugins() -> dict[str, str]:
    """Import + register all enabled plugins. Returns {name: status}."""
    status: dict[str, str] = {}
    for name, modpath in PLUGIN_MODULES.items():
        if not _manifest_enabled(name):
            status[name] = "disabled"
            continue
        try:
            mod = importlib.import_module(modpath)
        except Exception as e:  # noqa: BLE001 — missing module/dep is non-fatal
            status[name] = f"unavailable ({type(e).__name__})"
            log.warning("plugin %s not loaded: %s", name, e)
            continue
        register = getattr(mod, "register", None)
        if callable(register):
            try:
                register(registry)
                status[name] = "loaded"
            except Exception as e:  # noqa: BLE001
                status[name] = f"register-failed ({type(e).__name__})"
                log.warning("plugin %s register() failed: %s", name, e)
        else:
            status[name] = "no register()"
    log.info("plugins: %s", status)
    return status

# Packaging Hinton as a Windows desktop app

This directory turns Hinton into a native, double-click Windows desktop
application (a pywebview / EdgeChromium window — **not** the browser dev
server), then wraps it in a single installer `Hinton-Setup.exe`.

| File | Purpose |
|------|---------|
| `packaging/hinton.spec` | PyInstaller spec — windowed onedir build named **Hinton** |
| `scripts/build_app.ps1` | Installs PyInstaller + pywebview, runs the spec, prints `dist\Hinton` |
| `packaging/installer.iss` | Inno Setup script — packs `dist\Hinton` into `Hinton-Setup.exe` |

> **Naming note.** Only the *visible product brand* is "Hinton". The on-disk
> project directory (`C:\Users\_maX\openlm`), the `harness` python package, and
> the `OPENLM_` environment-variable prefix are intentionally **unchanged**, so
> user data still lives under `%LOCALAPPDATA%\OpenLM`.

---

## 1. Run in development (no build)

The GUI entry point is `python -m harness.main` (no `--serve`). It opens a
native pywebview window pointing at `frontend/index.html`.

```powershell
pip install pywebview            # native window backend (EdgeChromium on Win)
python -m harness.main           # native desktop window

# Browser / no-deps fallback (mock model, stdlib only):
python scripts\fetch_vendor.py   # once, to vendor the render libs
.\scripts\run.ps1 -Serve -Mock
```

If `pywebview` is missing, `harness.main` automatically falls back to the
browser dev server, so the native window only appears when pywebview is present.

---

## 2. Build the desktop .exe with PyInstaller

```powershell
.\scripts\build_app.ps1          # add -Clean to wipe build\ and dist\ first
```

This installs `pyinstaller` + `pywebview`, then runs:

```powershell
python -m PyInstaller packaging\hinton.spec --noconfirm --clean
```

Result: a windowed (no console) onedir app at

```
dist\Hinton\Hinton.exe
dist\Hinton\_internal\        <- python runtime, harness\, frontend\, plugins\, .NET bridge
```

What the spec does:

- **Windowed**: `console=False` — no terminal window pops up.
- **onedir** (not onefile): faster start-up and the EdgeChromium / pythonnet
  bridge behaves better unpacked.
- **add-data** bundles the *entire* `frontend/` tree (so `index.html` and
  `frontend/vendor/*` load at runtime) and the *entire* `plugins/` tree (the
  `manifest.json` files the loader reads) at the **bundle root**.
- **collect_submodules("harness")** so the lazily-`importlib`-loaded plugin
  implementations under `harness.tools.*` are included.
- **Hidden imports** for the pywebview Windows backend
  (`webview.platforms.winforms`, `webview.platforms.edgechromium`) and the .NET
  bridge (`clr`, `clr_loader`, `pythonnet`, `cffi`) that PyInstaller's static
  analysis cannot see.
- **Excludes** `models/` and `data/` — they are created at runtime / downloaded
  on first run — and excludes heavy optional deps (`torch`,
  `sentence_transformers`, `weasyprint`, `chromadb`) to keep the build small;
  the app degrades gracefully without them. Remove an exclude to bundle that
  feature.

> Runtime note: the EdgeChromium backend needs the **WebView2 Runtime**, which
> ships with Windows 11 (and modern Windows 10). On a bare machine, install the
> Evergreen WebView2 Runtime from Microsoft.

---

## 3. config.py and the frozen-path note (IMPORTANT)

`harness/config.py` derives every path from `__file__`:

```python
HARNESS_DIR  = Path(__file__).resolve().parent      # <root>/harness
ROOT_DIR     = HARNESS_DIR.parent                    # <root>
FRONTEND_DIR = ROOT_DIR / "frontend"
PLUGINS_DIR  = ROOT_DIR / "plugins"
MODELS_DIR   = Path(os.environ.get("OPENLM_MODELS_DIR", ROOT_DIR / "models"))
DATA_DIR     = Path(os.environ.get("OPENLM_DATA_DIR",  ROOT_DIR / "data"))
...
for _d in (DATA_DIR, MODELS_DIR, ATTACHMENTS_DIR, GENERATED_DIR, NOTEBOOK_DIR):
    _d.mkdir(parents=True, exist_ok=True)            # <- runs at IMPORT time
```

When PyInstaller freezes the app, the `harness` package lives at
`dist\Hinton\_internal\harness`, so at runtime:

- `ROOT_DIR == dist\Hinton\_internal` (i.e. `sys._MEIPASS` for onedir).

### `frontend/` and `plugins/` — already handled, **no edit required**

Because the spec drops the whole `frontend/` and `plugins/` trees at the bundle
root, they land at `_internal\frontend` and `_internal\plugins`. That is exactly
`ROOT_DIR / "frontend"` and `ROOT_DIR / "plugins"`, so `FRONTEND_DIR` and
`PLUGINS_DIR` resolve correctly **without touching config.py**.

### `data/` and `models/` — the one problem to fix

`ROOT_DIR` is inside the install folder (`C:\Program Files\Hinton\_internal`),
which is **not writable** for a per-machine install, yet config.py tries to
`mkdir` `data/` and `models/` there at import. The robust fix is to redirect the
*writable* dirs to `%LOCALAPPDATA%\OpenLM` when frozen.

You can do this **without editing config.py** by setting environment variables
before launch (config.py already honours `OPENLM_DATA_DIR` / `OPENLM_MODELS_DIR`)
— e.g. via a launcher `.bat`. But the cleaner, recommended approach is a tiny,
**minimal** edit to `harness/config.py`. Replace the path block (lines ~18-24)
with:

```python
import sys

if getattr(sys, "frozen", False):
    # PyInstaller onedir: bundle root holds frontend/ and plugins/.
    ROOT_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # Writable user data goes outside the (read-only) install dir.
    _USER_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OpenLM"
else:
    HARNESS_DIR = Path(__file__).resolve().parent
    ROOT_DIR = HARNESS_DIR.parent
    _USER_DIR = ROOT_DIR

FRONTEND_DIR = ROOT_DIR / "frontend"
PLUGINS_DIR  = ROOT_DIR / "plugins"

MODELS_DIR = Path(os.environ.get("OPENLM_MODELS_DIR", _USER_DIR / "models"))
DATA_DIR   = Path(os.environ.get("OPENLM_DATA_DIR",  _USER_DIR / "data"))
```

Everything below (`DB_PATH`, `ATTACHMENTS_DIR`, the `mkdir` loop, …) stays
unchanged: `DATA_DIR` / `MODELS_DIR` now point at `%LOCALAPPDATA%\OpenLM`, which
is always writable, while `FRONTEND_DIR` / `PLUGINS_DIR` resolve into the bundle.

> The user-data folder name stays `OpenLM` (matching the unchanged `OPENLM_`
> env-var prefix and `harness` package), even though the visible app is Hinton.
> This packaging task does **not** apply the config.py edit (the `harness/`
> tree is out of scope here). Apply it yourself before shipping a per-machine
> installer, or run the app with `OPENLM_DATA_DIR` / `OPENLM_MODELS_DIR` pointed
> at a writable path.

---

## 4. Compile the installer with Inno Setup

1. Install [Inno Setup](https://jrsoftware.org/isdl.php) (provides `ISCC.exe`).
2. Build `dist\Hinton` first (section 2).
3. From the project root:

   ```powershell
   ISCC packaging\installer.iss
   ```

   or open `packaging\installer.iss` in the Inno Setup IDE and press **Build**
   (F9).

Output: `packaging\Hinton-Setup.exe`.

The installer:

- installs under `{autopf}\Hinton` (`C:\Program Files\Hinton`),
- creates a **Start Menu** shortcut and an optional **desktop** shortcut
  (unchecked task on the wizard),
- registers an **uninstaller** (Apps & Features + Start Menu entry),
- shows a **first-run note** about downloading the model,
- leaves user data under `%LOCALAPPDATA%\OpenLM` in place on uninstall.

---

## 5. What the end user does on first launch

1. Launch **Hinton** from the Start Menu / desktop.
2. With no model weights present, the app runs in offline **mock** mode
   (`config.MOCK_LLM == True`) so the UI is fully explorable immediately.
3. To enable the real local model, download the weights once:

   ```powershell
   python scripts\download_models.py        # MTP drafter + embedding model (~12 GB)
   ```

   Place the GGUF weights under the models dir (`%LOCALAPPDATA%\OpenLM\models`
   after the config edit, or set `OPENLM_MODELS_DIR`).
4. Provide a SYCL + MTP `llama-server.exe` on `PATH`, or point
   `OPENLM_LLAMA_SERVER` at it. When a real `llama-server` is found, the app
   automatically switches off mock mode.
5. Restart Hinton — it now serves the real on-device model.

# Packaging Hinton (Windows)

## Why a ZIP, not an installer .exe

Hinton ships the Gemma 4 **E4B** model (~4.9 GB) inside the app so it runs the
real model offline from first launch. **Windows cannot execute a `.exe` larger
than ~4 GB** (`CreateProcess` → `ERROR_BAD_EXE_FORMAT`), and every installer
tool hits the same wall — Inno Setup refuses (`Disk spanning must be enabled
... larger than 4200000000 bytes`), and a 7‑Zip SFX builds but won't run. So the
model can't live in a runnable installer exe. Distribution is therefore a **ZIP**.

## Artifacts

| File | Size | What the user does |
|------|------|--------------------|
| `Hinton-Full.zip` | ~5 GB | Extract → run `Hinton\Hinton.exe`. Real Gemma 4 E4B runs locally, fully offline, **zero config**. |
| `Hinton-12B-Plugin.zip` | ~6.5 GB | Extract → run `12B 모델 설치.cmd` (drops the 12B model into `%LOCALAPPDATA%\Hinton\models`) → restart Hinton to enable 12B escalation. |

`Hinton-Full.zip` also contains `README.txt` and `바로가기 만들기.cmd` (creates
Desktop + Start Menu shortcuts to the extracted `Hinton.exe`).

## Build

```powershell
# Prereqs: pip install pyinstaller ; winget install 7zip.7zip
#          models present: scripts\get_gemma.py --size e4b  (and --size g4-12b for the plugin)
.\scripts\build_zip.ps1            # PyInstaller build (dist\Hinton) + both ZIPs
.\scripts\build_zip.ps1 -SkipBuild # re-zip an existing dist\Hinton only
```

`build_zip.ps1` calls `build_app.ps1` (PyInstaller, spec `packaging\hinton.spec`)
then stores `dist\Hinton` + the helper files into the ZIPs (`-mx0`, no
compression — the GGUF is already-compressed weights).

## How the frozen app finds things (see `harness/config.py`)

* `FROZEN` is true under PyInstaller → `ROOT_DIR = sys._MEIPASS` (the bundle).
* Bundled, read‑only: `ROOT_DIR/bin/llama-server.exe`,
  `ROOT_DIR/models/gemma-4-E4B_q4_0-it.gguf`, `ROOT_DIR/frontend`, `ROOT_DIR/plugins`.
* Writable user data: `%LOCALAPPDATA%\Hinton` (`data\`, `models\`). The 12B
  plugin drops its weights into `%LOCALAPPDATA%\Hinton\models`; config resolves
  it there and enables escalation, else escalation stays disabled.
* Frozen default model profile is `generic` (the bundled prebuilt CPU
  llama-server + a plain GGUF); source checkouts default to `gemma`.

## Verified

The bundled `dist\Hinton\Hinton.exe`, launched with **no environment variables**,
reports `active=e4b mock=False` and answers from the real Gemma 4 E4B — i.e.
extract-and-run gives the real model with zero configuration, fully offline.

## Dev run (no packaging)

```powershell
$env:OPENLM_MOCK="1"; python -m harness.main --serve   # browser, mock model
# real model from a source checkout:
$env:OPENLM_MODEL_PROFILE="generic"
$env:OPENLM_E4B_MODEL="...\models\gemma-4-E4B_q4_0-it.gguf"
$env:OPENLM_LLAMA_SERVER="...\bin\llama-server.exe"
python -m harness.main            # pywebview window
```

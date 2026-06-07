# Packaging Hinton (Windows)

Hinton ships as a **standalone Tauri desktop app** with **no system-Python
dependency**: the native WebView2 window (`hinton-tauri`) launches an **embedded
Python** runtime to run the `harness` backend (`python -m harness.main --serve`)
and loads its local URL. The frozen PyInstaller build and the offline ZIP
distribution were **removed** — Tauri is the only supported packaging.

The backend core is **stdlib-only**, so the official Windows *embeddable* Python
(interpreter + full stdlib, ~25 MB) is all that's bundled; the user never installs
Python. Optional heavy plugins (torch/weasyprint, doc-gen, embeddings) are not
required to run.

## Build / run

```powershell
# Prereqs (developer machine): Rust toolchain (cargo), a Python to run the
# fetch scripts, WebView2 runtime (preinstalled on Win11).
python scripts\get_python.py          # -> python-embed\  (embeddable runtime; gitignored)
python scripts\get_llama_server.py    # -> bin\llama-server.exe (+ ggml-vulkan.dll)
python scripts\get_gemma.py --size e4b      # -> models\  (resident model)
python scripts\get_gemma.py --size g4-12b   # (optional) 12B escalation

cd hinton-tauri\src-tauri
cargo build --release                 # dev exe -> target\release\hinton.exe
cargo tauri build                     # standalone installer (bundles
                                      #   python-embed/ harness/ frontend/ bin/ plugins/)
```

Run the dev build: `hinton-tauri\src-tauri\target\release\hinton.exe`.
Installer output: `target\release\bundle\msi\Hinton_<ver>_x64_en-US.msi`
(installs to Program Files + Start-Menu shortcut with the app icon).

> **Installer target = MSI (WiX).** `bundle.targets` is `["msi"]`. NSIS would also
> work but its toolchain is fetched from GitHub at build time, which is
> unreliable on some networks (connection resets); WiX is cached locally, so MSI
> builds offline-reliably. Switch to `["nsis"]` (or both) if you have a stable
> GitHub connection.

> **Icon:** `scripts/_makeicon.py` renders the 1024px source (`hinton-tauri/icon-src.png`,
> rounded-square brand gradient + white "H"); `cargo tauri icon ../icon-src.png`
> regenerates `src-tauri/icons/` (incl. `icon.ico` used by the exe + shortcut).

> **Model distribution = first-run download.** `models/` is NOT bundled (the GGUFs
> are 5–7 GB; installer size). On first launch the backend downloads the resident
> E4B model into `%LOCALAPPDATA%\OpenLM\models` with a **progress window**
> (`harness/boot.py` → `Api.get_boot_status` → `ui/loading.html`: the loading
> screen shows a progress bar and only enters the app when the model is `ready`).
> Everything else needed to run is in the installer, so the app is self-contained.
> The Tauri shell points the backend at writable `%LOCALAPPDATA%\OpenLM\{data,models}`
> because the install dir is read-only.

## How the Tauri shell works (`hinton-tauri/src-tauri/src/main.rs`)

* **Root resolution** (`repo_root`): `HINTON_ROOT` env → Tauri `resource_dir()`
  (installed app, where `bundle.resources` places `harness/`, `python-embed/`,
  `bin/`, ...) → repo root (dev, walking up from the exe).
* **Python** (`python_exe`): prefers the bundled `python-embed\python.exe`
  (sibling of `harness/`); falls back to a `python` on PATH only if the bundle is
  absent (bare source clone). The embeddable interpreter resolves `import harness`
  via its `pythonNNN._pth` (which adds `..`, the dir that holds `harness/`).
* Spawns `python -m harness.main --serve --port <free>` with env
  `OPENLM_MODEL_PROFILE=generic`, `OPENLM_LLAMA_SERVER=bin\llama-server.exe`,
  `OPENLM_E4B_MODEL=models\...gguf`, `CREATE_NO_WINDOW` (no console flash).
* `loading.html` polls the `backend_url` command, then navigates the window to
  the backend once it is up. On window close, the child backend is killed.
* Verified: the rebuilt `hinton.exe` spawns `python-embed\python.exe` (not system
  Python) and drives the real E4B (`mock=False`) end to end.

## GPU acceleration (cross-vendor, verified on Vulkan b9548)

The bundled `bin/llama-server.exe` is the **Vulkan** build (ships
`ggml-vulkan.dll`) — one binary GPU-accelerates on **Intel, AMD and NVIDIA**
(CUDA=NVIDIA-only, ROCm=AMD-only, SYCL=Intel-only). NPUs are not used —
llama.cpp has no NPU backend (that would need OpenVINO, Intel-only).

### Memory / GPU offload (`config._generic_args`)

* **Auto-fit (`OPENLM_NGL=auto`, default):** `-ngl` is omitted so llama.cpp
  places as many layers as fit on the GPU (~8 GB device-local on Lunar Lake)
  and keeps the rest in CPU/system RAM — using the full **16 GB unified
  memory**. E4B (~5 GB) lands entirely on the GPU (~24 tok/s); the 12B q4
  (~7 GB + KV/compute > 8 GB) is split GPU+CPU and runs (~12 tok/s) instead of
  aborting. NOTE: forcing `-ngl 999` makes llama.cpp **abort** for the 12B
  (`failed to fit params ... already set by user to 999`). Pin layers with
  `OPENLM_NGL=<n>` (0 = pure CPU).

### KV-cache quantization

`-fa on --cache-type-k q8_0 --cache-type-v q4_0` (KV cache ~3/8 of f16). Two
build gotchas, both handled: flash attention needs the value form `-fa on`
(bare `-fa` swallows the next arg), and quantizing the **V** cache **hangs the
warmup without flash attention** (so V is only quantized when `-fa` is on).
Override via `OPENLM_FLASH_ATTN` / `OPENLM_CACHE_TYPE_K` / `OPENLM_CACHE_TYPE_V`.

### Speculative decoding (draft) — not usable on the cross-vendor Vulkan build

Both draft approaches were tested and rejected:
* **MTP assistant** (`--spec-type draft-mtp`): the official Gemma-4 assistant
  heads are architecture `gemma4_mtp`, which mainline llama.cpp does **not**
  implement (`unknown model architecture: 'gemma4_mtp'`); other conversions load
  as plain `gemma4` and report `model doesn't contain MTP layers`. MTP only
  works on the Intel SYCL+MTP / ik-llama forks.
* **E2B as a plain draft** (`--spec-type draft-simple`): E4B + E2B exceed the
  8 GB GPU (crash), and a 2B→4B ratio gives little speedup even on CPU.

So no draft is wired by default. The draft GGUFs in `models/` are unused on this
runtime.

## Dev run (no Tauri)

```powershell
$env:OPENLM_MOCK="1"; python -m harness.main --serve   # browser, mock model
# real model from a source checkout:
$env:OPENLM_MODEL_PROFILE="generic"
$env:OPENLM_LLAMA_SERVER="...\bin\llama-server.exe"
$env:OPENLM_E4B_MODEL="...\models\gemma-4-E4B_q4_0-it.gguf"
python -m harness.main --serve
```

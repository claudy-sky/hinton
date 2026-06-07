# Packaging Hinton (Windows)

Hinton ships as a **Tauri desktop app**. The native WebView2 window
(`hinton-tauri`) launches the Python backend as a sidecar
(`python -m harness.main --serve`) and loads its local URL. The frozen
PyInstaller build and the offline ZIP distribution were **removed** — Tauri is
the only supported packaging.

## Build / run

```powershell
# Prereqs: Rust toolchain (cargo), Python 3.11/3.12, WebView2 runtime (preinstalled on Win11),
#          models in models\ (scripts\get_gemma.py) and bin\llama-server.exe (scripts\get_llama_server.py).
cd hinton-tauri\src-tauri
cargo build --release          # -> target\release\hinton.exe
# or a full installer (NSIS/MSI):
cargo tauri build
```

Run the built app: `hinton-tauri\src-tauri\target\release\hinton.exe`.

## How the Tauri shell works (`hinton-tauri/src-tauri/src/main.rs`)

* Resolves the repo root (env `HINTON_ROOT`, else walks up from the exe).
* Spawns `python -m harness.main --serve --port <free>` as a child, with env
  `OPENLM_MODEL_PROFILE=generic`, `OPENLM_LLAMA_SERVER=bin\llama-server.exe`,
  `OPENLM_E4B_MODEL=models\gemma-4-E4B_q4_0-it.gguf` (so it runs the real model
  with no manual setup), `CREATE_NO_WINDOW` so no console flashes.
* `loading.html` polls the `backend_url` command, then navigates the window to
  the backend once it is up. On window close, the child backend is killed.
* Because the backend is the live `harness` source, edits take effect on the
  next launch (no rebuild of Python needed; only `cargo build` for Rust changes).

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

<#
  Builds the distributable ZIPs for Hinton.

  Windows cannot execute a .exe larger than ~4 GB, so the 4.9 GB E4B model
  cannot live inside a runnable installer exe. Distribution is therefore a ZIP:

    packaging\Hinton-Full.zip        app + bundled Gemma 4 E4B  -> extract, run Hinton\Hinton.exe (real model, fully offline)
    packaging\Hinton-12B-Plugin.zip  optional 12B escalation model

  Usage:
    .\scripts\build_zip.ps1            # PyInstaller build + both zips
    .\scripts\build_zip.ps1 -SkipBuild # zip the existing dist\Hinton only
#>
param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path

$sevenz = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") |
          Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenz) { throw "7-Zip (7z.exe) not found. Install it: winget install 7zip.7zip" }

if (-not $SkipBuild) { & "$root\scripts\build_app.ps1" }

$dist = "$root\dist\Hinton"
if (-not (Test-Path "$dist\Hinton.exe")) { throw "dist\Hinton not built (run build_app.ps1 first)" }

$full = "$root\packaging\Hinton-Full.zip"
if (Test-Path $full) { Remove-Item $full -Force }
& $sevenz a -tzip -mx0 $full $dist "$root\packaging\zip\README.txt" "$root\packaging\zip\바로가기 만들기.cmd"
Write-Host "Built $full"

$b12 = "$root\models\gemma-4-12b-it-qat-q4_0.gguf"
if (Test-Path $b12) {
    $plugin = "$root\packaging\Hinton-12B-Plugin.zip"
    if (Test-Path $plugin) { Remove-Item $plugin -Force }
    & $sevenz a -tzip -mx0 $plugin $b12 "$root\packaging\zip\12B 모델 설치.cmd"
    Write-Host "Built $plugin"
} else {
    Write-Host "12B model not present (scripts\get_gemma.py --size g4-12b) — skipped 12B plugin zip."
}

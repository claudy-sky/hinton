#requires -Version 5.1
<#
.SYNOPSIS
    Build the Hinton Windows desktop app with PyInstaller.

.DESCRIPTION
    Installs PyInstaller (and the runtime GUI dependency pywebview), then runs
    PyInstaller against packaging/hinton.spec to produce a windowed onedir app
    at dist/Hinton/Hinton.exe.

    Run from anywhere; the script locates the project root from its own path.

.EXAMPLE
    .\scripts\build_app.ps1
#>
[CmdletBinding()]
param(
    # Wipe previous build/ and dist/ output before building.
    [switch] $Clean
)

$ErrorActionPreference = 'Stop'

# --- Locate project root (this script lives in <root>\scripts) ----------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SpecPath    = Join-Path $ProjectRoot 'packaging\hinton.spec'
$DistPath    = Join-Path $ProjectRoot 'dist\Hinton'

Write-Host "Hinton packaging build" -ForegroundColor Cyan
Write-Host "  Project root : $ProjectRoot"
Write-Host "  Spec file    : $SpecPath"

if (-not (Test-Path -LiteralPath $SpecPath)) {
    throw "Spec file not found: $SpecPath"
}

# --- Resolve the Python interpreter -------------------------------------------
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    $Python = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
    throw 'Python was not found on PATH. Install Python 3.11/3.12 (or 3.14) and retry.'
}
Write-Host "  Python       : $Python"

# --- Install build + runtime dependencies -------------------------------------
Write-Host "`nInstalling PyInstaller and pywebview..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)." }

& $Python -m pip install pyinstaller pywebview
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)." }

# --- Optional clean -----------------------------------------------------------
if ($Clean) {
    Write-Host "`nCleaning previous build output..." -ForegroundColor Cyan
    foreach ($dir in @('build', 'dist')) {
        $p = Join-Path $ProjectRoot $dir
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force
            Write-Host "  removed $p"
        }
    }
}

# --- Run PyInstaller ----------------------------------------------------------
Write-Host "`nRunning PyInstaller..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller $SpecPath --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

# --- Report -------------------------------------------------------------------
if (Test-Path -LiteralPath (Join-Path $DistPath 'Hinton.exe')) {
    Write-Host "`nBuild succeeded." -ForegroundColor Green
    Write-Host "  App folder : $DistPath"
    Write-Host "  Executable : $(Join-Path $DistPath 'Hinton.exe')"
    Write-Host "`nNext: compile packaging\installer.iss with Inno Setup to produce Hinton-Setup.exe."
}
else {
    throw "Build finished but Hinton.exe was not found under $DistPath."
}

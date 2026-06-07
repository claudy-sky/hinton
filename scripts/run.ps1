<#
  Hinton launcher.

  Examples:
    .\scripts\run.ps1                 # GUI (pywebview) if installed, else dev server
    .\scripts\run.ps1 -Serve          # force the browser dev server
    .\scripts\run.ps1 -Serve -Mock    # browser + mock model (no weights needed)
    .\scripts\run.ps1 -Mock -Port 8095
#>
param(
  [switch]$Serve,
  [switch]$Mock,
  [int]$Port = 8090
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$env:PYTHONPATH = $root
if ($Mock) { $env:OPENLM_MOCK = "1" }

$cliArgs = @()
if ($Serve) { $cliArgs += @("--serve", "--port", $Port) }

Write-Host "Hinton 시작 (root=$root, mock=$($Mock.IsPresent), serve=$($Serve.IsPresent))"
if ($Serve) { Write-Host "브라우저에서 http://127.0.0.1:$Port 를 여세요." }
python -m harness.main @cliArgs

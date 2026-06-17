$ErrorActionPreference = "Stop"

$PackageName = "local-repo-harness"
$PackageVersion = if ($env:REPO_HARNESS_VERSION) { $env:REPO_HARNESS_VERSION } else { "latest" }
$BunInstall = if ($env:BUN_INSTALL) { $env:BUN_INSTALL } else { Join-Path $HOME ".bun" }
$BunBin = Join-Path $BunInstall "bin"

function Add-BunToPath {
  if (Test-Path $BunBin) {
    $env:PATH = "$BunBin$([System.IO.Path]::PathSeparator)$env:PATH"
  }
}

function Test-Command($Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if ($env:REPO_HARNESS_DRY_RUN -eq "1") {
  Write-Host "DRY RUN: would ensure Bun, install $PackageName@$PackageVersion, and verify local-repo-harness --version."
  exit 0
}

Add-BunToPath

if (-not (Test-Command "bun")) {
  Write-Host "Installing Bun runtime..."
  Invoke-RestMethod https://bun.sh/install.ps1 | Invoke-Expression
  Add-BunToPath
}

if (-not (Test-Command "bun")) {
  throw "Bun install completed, but bun is still not on PATH."
}

$PackageSpec = "$PackageName@$PackageVersion"
Write-Host "Installing $PackageSpec with Bun..."
& bun add -g $PackageSpec

Add-BunToPath
if (-not (Test-Command "local-repo-harness")) {
  throw "local-repo-harness is not on PATH after installation."
}

$Version = (& local-repo-harness --version)
if (-not $Version) {
  throw "local-repo-harness installed, but version readback failed."
}

Write-Host "local-repo-harness $Version installed."
Write-Host ""
Write-Host "Next:"
Write-Host "  local-repo-harness adopt --dry-run"
Write-Host "  local-repo-harness init   # optional machine bootstrap"

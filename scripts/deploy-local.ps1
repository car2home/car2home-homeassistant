# Deploy the car2home plugin from this repo to the CasaOS Home Assistant share.
#
# Usage (from anywhere, in PowerShell):
#     .\car2home-homeassistant\scripts\deploy-local.ps1
#
# Assumes the CasaOS SMB share is mapped/accessible at \\CASAOS\AppData on Windows.
# Fails fast if:
#   - the share is not reachable
#   - the destination path doesn't exist (wrong HA config dir)
#   - the copy fails
#
# Does NOT restart HA — stop the HA container in CasaOS BEFORE running this,
# start it again AFTER. Rationale: a running container regenerates __pycache__
# mid-copy and can load stale bytecode.

$ErrorActionPreference = 'Stop'

# Resolve the repo paths relative to this script so it works from any CWD.
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcPluginDir  = Join-Path $ScriptDir '..\custom_components\car2home'
$SrcPluginDir  = (Resolve-Path $SrcPluginDir).Path
$ShareRoot     = '\\192.168.15.180\casaos\AppData'
$DestParent    = Join-Path $ShareRoot 'homeassistant\config\custom_components'
$DestPluginDir = Join-Path $DestParent 'car2home'

# --- Sanity checks ----------------------------------------------------------

if (-not (Test-Path -LiteralPath $SrcPluginDir -PathType Container)) {
    Write-Error "source plugin folder not found: $SrcPluginDir"
}

if (-not (Test-Path -LiteralPath $ShareRoot -PathType Container)) {
    Write-Error "$ShareRoot is not reachable. Map/connect the CasaOS share in Explorer first."
}

if (-not (Test-Path -LiteralPath $DestParent -PathType Container)) {
    Write-Error "destination folder not found: $DestParent`n       Check that the HA config path is correct for your CasaOS install."
}

# --- Remove stale __pycache__ and old copy ---------------------------------
# (Windows has no equivalent of macOS xattrs, so step 1 from the .sh is dropped.)
Write-Host '[1/4] Removing old plugin folder at destination (if present)...'
if (Test-Path -LiteralPath $DestPluginDir) {
    Remove-Item -LiteralPath $DestPluginDir -Recurse -Force -Confirm:$false
}

# --- Copy ------------------------------------------------------------------
# Destination was wiped above, so a plain recursive copy is sufficient.
Write-Host "[2/4] Copying plugin -> $DestPluginDir..."
New-Item -ItemType Directory -Path $DestPluginDir -Force | Out-Null
# NOTE: -Path (not -LiteralPath) so the trailing \* wildcard expands. With
# -LiteralPath the '*' is treated as a literal filename, the copy silently
# matches nothing, and the destination ends up empty.
Copy-Item -Path (Join-Path $SrcPluginDir '*') -Destination $DestPluginDir -Recurse -Force

# --- Refresh mtimes so Python regenerates bytecode from the new source ------
Write-Host '[3/4] Refreshing file mtimes...'
$now = Get-Date
Get-ChildItem -LiteralPath $DestPluginDir -Recurse -File | ForEach-Object {
    $_.LastWriteTime = $now
}

# --- Show the deployed version ---------------------------------------------
Write-Host '[4/4] Verification:'
Select-String -LiteralPath (Join-Path $DestPluginDir 'manifest.json') -Pattern '"version"' |
    Select-Object -First 1 |
    ForEach-Object { $_.Line }

Write-Host ''
Write-Host 'Done. Start the Home Assistant container in CasaOS and reload the config flow in an incognito window.'

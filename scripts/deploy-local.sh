#!/usr/bin/env bash
# Deploy the car2home plugin from this repo to the CasaOS Home Assistant share.
#
# Usage (from anywhere):
#     ./car2home-homeassistant/scripts/deploy-local.sh
#
# Assumes the CasaOS SMB share is mounted at /Volumes/CASAOS on macOS.
# Fails fast if:
#   - the share is not mounted
#   - the destination path doesn't exist (wrong HA config dir)
#   - rsync / touch fails
#
# Does NOT restart HA — stop the HA container in CasaOS BEFORE running this,
# start it again AFTER. Rationale: a running container regenerates __pycache__
# mid-copy and can load stale bytecode.

set -euo pipefail

# Resolve the repo paths relative to this script so it works from any CWD.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
SRC_PLUGIN_DIR="${SCRIPT_DIR}/../custom_components/car2home"
DEST_PARENT="/Volumes/CASAOS/AppData/homeassistant/config/custom_components"
DEST_PLUGIN_DIR="${DEST_PARENT}/car2home"

# --- Sanity checks ----------------------------------------------------------

if [[ ! -d "${SRC_PLUGIN_DIR}" ]]; then
  echo "ERROR: source plugin folder not found: ${SRC_PLUGIN_DIR}" >&2
  exit 1
fi

if [[ ! -d "/Volumes/CASAOS" ]]; then
  echo "ERROR: /Volumes/CASAOS is not mounted. Mount the CasaOS share in Finder first." >&2
  exit 1
fi

if [[ ! -d "${DEST_PARENT}" ]]; then
  echo "ERROR: destination folder not found: ${DEST_PARENT}" >&2
  echo "       Check that the HA config path is correct for your CasaOS install." >&2
  exit 1
fi

# --- Clean xattrs on the source --------------------------------------------
# macOS attaches com.apple.quarantine and similar extended attributes that SMB
# shares can't write, which makes Finder fail with error -1407. Stripping xattrs
# on the source before copying sidesteps that entirely.
echo "[1/5] Stripping macOS extended attributes from source..."
xattr -cr "${SRC_PLUGIN_DIR}"

# --- Remove stale __pycache__ and old copy ---------------------------------
echo "[2/5] Removing old plugin folder at destination (if present)..."
if [[ -d "${DEST_PLUGIN_DIR}" ]]; then
  rm -rf "${DEST_PLUGIN_DIR}"
fi

# --- Copy with cp -R (BSD rsync on macOS lacks --no-xattrs / --no-perms) ----
# The `xattr -cr` above already stripped the macOS-specific metadata that was
# causing Finder error -1407, so plain `cp` works now. Destination was wiped in
# step 2, so no --delete semantics needed.
echo "[3/5] Copying plugin → ${DEST_PLUGIN_DIR}..."
mkdir -p "${DEST_PLUGIN_DIR}"
cp -R "${SRC_PLUGIN_DIR}/." "${DEST_PLUGIN_DIR}/"

# --- Refresh mtimes so Python regenerates bytecode from the new source ------
echo "[4/5] Refreshing file mtimes..."
find "${DEST_PLUGIN_DIR}" -type f -exec touch {} \;

# --- Show the deployed version ---------------------------------------------
echo "[5/5] Verification:"
grep '"version"' "${DEST_PLUGIN_DIR}/manifest.json" | head -1

echo
echo "Done. Start the Home Assistant container in CasaOS and reload the config flow in an incognito window."

#!/usr/bin/env bash
# Uninstaller: stop the LaunchAgent and remove the installed copy of Blaster Mac Client.
# Logs in ~/Library/Logs/blaster-mac-client are left in place.
#
# Usage: ./uninstall.sh

set -euo pipefail

LABEL="com.blaster-mac-client"
INSTALL_DIR="$HOME/Library/Application Support/blaster-mac-client"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
rm -f "$PLIST_DEST"
rm -rf "$INSTALL_DIR"

echo "Blaster Mac Client removed (agent unloaded, $INSTALL_DIR deleted)."
echo "Logs kept at $HOME/Library/Logs/blaster-mac-client"

#!/usr/bin/env bash
# Installer: copy Blaster Mac Client into ~/Library/Application Support and run it at login.
#
# The copy matters: a LaunchAgent inherits no privacy (TCC) grants, so launchd cannot
# read ~/Desktop, ~/Documents, ~/Downloads or iCloud Drive. Starting the app from one of
# those folders fails with "Operation not permitted". ~/Library/Application Support is
# not protected, so the agent runs with no permission prompts at all.
#
# Usage: ./install.sh
# Uninstall: ./uninstall.sh

set -euo pipefail
cd "$(dirname "$0")"
SRC_DIR="$(pwd)"

LABEL="com.blaster-mac-client"
INSTALL_DIR="$HOME/Library/Application Support/blaster-mac-client"
LOG_DIR="$HOME/Library/Logs/blaster-mac-client"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$SRC_DIR" == "$INSTALL_DIR" ]]; then
  echo "Error: run install.sh from your copy of the project, not from $INSTALL_DIR" >&2
  exit 1
fi

# Stop any previous install before its files are replaced.
launchctl unload "$PLIST_DEST" 2>/dev/null || true

mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"

# Truncate legacy launchd capture files so a prior flood does not linger.
: > "$LOG_DIR/stdout.log"
: > "$LOG_DIR/stderr.log"

echo "Installing to $INSTALL_DIR"
rsync -a --delete \
	--exclude '.venv/' \
	--exclude '.git/' \
	--exclude '.github/' \
	--exclude 'dist/' \
	--exclude 'logs/' \
	--exclude '__pycache__/' \
	--exclude '.pytest_cache/' \
	--exclude '.DS_Store' \
	--exclude 'config.yaml' \
	"$SRC_DIR/" "$INSTALL_DIR/"

if [[ -f "$INSTALL_DIR/config.yaml" ]]; then
  echo "Keeping existing config: $INSTALL_DIR/config.yaml"
else
  cp "$SRC_DIR/config.yaml" "$INSTALL_DIR/config.yaml"
fi

# Build the venv here, in the interactive shell: launchd starts the agent with a minimal
# PATH and no user shell, so dependency installation cannot be deferred to first launch.
echo "Creating virtualenv and installing dependencies..."
rm -rf "$INSTALL_DIR/.venv"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# Use plistlib so path special characters are correctly encoded (avoids shell/XML injection)
INSTALL_DIR="$INSTALL_DIR" LOG_DIR="$LOG_DIR" python3 -c '
import os, sys, plistlib

TOKENS = {"INSTALL_DIR": os.environ["INSTALL_DIR"], "LOG_DIR": os.environ["LOG_DIR"]}

def substitute(obj):
    if isinstance(obj, str):
        for token, value in TOKENS.items():
            obj = obj.replace(token, value)
        return obj
    if isinstance(obj, list):
        return [substitute(i) for i in obj]
    if isinstance(obj, dict):
        return {k: substitute(v) for k, v in obj.items()}
    return obj

p = plistlib.load(sys.stdin.buffer)
plistlib.dump(substitute(p), sys.stdout.buffer)
' < com.blaster-mac-client.plist > "$PLIST_DEST"

launchctl load "$PLIST_DEST"

echo ""
echo "Blaster Mac Client is installed and running."
echo "  • Installed at: $INSTALL_DIR"
echo "  • Starts automatically at login, restarts if it exits or crashes"
echo "  • App log (rotated): $LOG_DIR/blaster.log"
echo "  • LaunchAgent capture: $LOG_DIR/stderr.log (warnings/errors only)"
echo ""
echo "Management UI: http://127.0.0.1:8765"
echo ""
echo "This folder is no longer used at runtime — the installed copy is. Re-run ./install.sh after changing the code."
echo "To remove: ./uninstall.sh"
echo ""

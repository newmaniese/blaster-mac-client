#!/usr/bin/env bash
# Light installer: set up Blaster Mac Client to run at login (LaunchAgent).
# Usage: ./install.sh
# Uninstall: launchctl unload ~/Library/LaunchAgents/com.blaster-mac-client.plist

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# Ensure run.sh is executable (e.g. after unzipping)
chmod +x run.sh 2>/dev/null || true

# Create logs directory for the plist
mkdir -p logs

# Install plist with this project path
PLIST_DEST="$HOME/Library/LaunchAgents/com.blaster-mac-client.plist"
# Use python for literal string replacement to avoid sed injection/failure with special characters in PROJECT_DIR
PROJECT_DIR="$PROJECT_DIR" python3 -c '
import os, sys, plistlib

def replace_dir(obj, d):
    if isinstance(obj, str): return obj.replace("PROJECT_DIR", d)
    if isinstance(obj, list): return [replace_dir(i, d) for i in obj]
    if isinstance(obj, dict): return {k: replace_dir(v, d) for k, v in obj.items()}
    return obj

try:
    if hasattr(plistlib, "load"):
        p = plistlib.load(sys.stdin.buffer)
        new_p = replace_dir(p, os.environ["PROJECT_DIR"])
        plistlib.dump(new_p, sys.stdout.buffer)
    else:
        # Fallback for Python < 3.9 if load/dump buffer are not supported
        sys.stdout.write(sys.stdin.read().replace("PROJECT_DIR", os.environ["PROJECT_DIR"]))
except Exception:
    sys.stdout.write(sys.stdin.read().replace("PROJECT_DIR", os.environ["PROJECT_DIR"]))
' < com.blaster-mac-client.plist > "$PLIST_DEST"

# Load (reload if already loaded)
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo ""
echo "Blaster Mac Client is installed and running."
echo "  • Starts automatically at login"
echo "  • Restarts if it exits or crashes"
echo "  • Logs: $PROJECT_DIR/logs/stdout.log  $PROJECT_DIR/logs/stderr.log"
echo ""
echo "To stop and disable: launchctl unload ~/Library/LaunchAgents/com.blaster-mac-client.plist"
echo ""

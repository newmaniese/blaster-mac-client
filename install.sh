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
sed "s|PROJECT_DIR|$PROJECT_DIR|g" com.blaster-mac-client.plist > "$PLIST_DEST"

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

#!/usr/bin/env bash
# Install (or reinstall) the folder watcher as a per-user launchd agent.
# It scans the input folder every 5 minutes, uploads new/changed date folders and queues them.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/com.musicbuddy.watcher.plist"
sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" "$REPO/watcher/com.musicbuddy.watcher.plist" > "$DEST"
launchctl bootout "gui/$(id -u)/com.musicbuddy.watcher" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Installed. Logs: ~/Library/Logs/musicbuddy-watcher.log"
echo "Run now:   launchctl kickstart -k gui/$(id -u)/com.musicbuddy.watcher"
echo "Uninstall: launchctl bootout gui/$(id -u)/com.musicbuddy.watcher && rm '$DEST'"

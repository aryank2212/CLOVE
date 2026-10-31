#!/usr/bin/env bash
# Starts CLOVE with your graphical session, no terminal needed: a systemd user service, `clove` (on a Mac: the
# launchd agent dev.clove.agent in ~/Library/LaunchAgents).
#   scripts/install_autostart.sh            install and enable it (it starts at the next login)
#   scripts/install_autostart.sh --now      ...and start it now (stop a terminal-started CLOVE first)
#   scripts/install_autostart.sh --remove   disable and remove it
# Logs: ~/.local/state/clove/clove.log and stderr.log, plus `journalctl --user -u clove`.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(uname)" = Darwin ]; then
  # macOS: a launchd agent in ~/Library/LaunchAgents, started at login and restarted if it crashes.
  label=dev.clove.agent
  plist="$HOME/Library/LaunchAgents/$label.plist"
  if [ "${1:-}" = --remove ]; then
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$plist"
    echo "Removed: CLOVE no longer starts with your session."; exit 0
  fi
  case "$dir" in *[\'\"\\\&\<\>]*) echo "The clove folder's path has a quote, backslash, & or <> in it; move it first." >&2; exit 1;; esac
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/state/clove"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>for i in \$(seq 120); do [ -x "$dir/run.sh" ] &amp;&amp; exec "$dir/run.sh" --background; sleep 1; done; echo "$dir is not mounted" &gt;&amp;2; exit 1</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardErrorPath</key><string>$HOME/.local/state/clove/stderr.log</string>
  <key>StandardOutPath</key><string>/dev/null</string>
</dict>
</plist>
PLIST
  plutil -lint "$plist" >/dev/null
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if [ "${1:-}" = --now ]; then
    launchctl bootstrap "gui/$(id -u)" "$plist"
    echo "CLOVE is running as a login agent."
  else                                     # launchd loads ~/Library/LaunchAgents at every login
    echo "Installed: CLOVE starts at your next login. Start it now with: scripts/install_autostart.sh --now"
  fi
  echo "macOS asks once for the Microphone; turn on Accessibility and Screen Recording for the python in $dir/.venv"
  echo "(System Settings > Privacy & Security) so windows, typing and screenshots work from the login agent."
  exit 0
fi
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/clove.service"

if [ "${1:-}" = --remove ]; then
  systemctl --user disable --now clove.service 2>/dev/null || true
  rm -f "$unit"; systemctl --user daemon-reload
  echo "Removed: CLOVE no longer starts with your session."; exit 0
fi
case "$dir" in *[\'\"\\%]*) echo "The clove folder's path has a quote, backslash or % in it; move it first." >&2; exit 1;; esac

mkdir -p "$(dirname "$unit")"
cat > "$unit" <<UNIT
[Unit]
Description=CLOVE voice assistant
Documentation=file://$dir/README.md
PartOf=graphical-session.target
After=graphical-session.target pipewire.service pipewire-pulse.service wireplumber.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
# The clove folder may be on a drive that is mounted after login: wait for it (two minutes at most).
ExecStartPre=/bin/sh -c 'for i in \$(seq 120); do [ -x "$dir/run.sh" ] && exit 0; sleep 1; done; echo "$dir is not mounted" >&2; exit 1'
ExecStart="$dir/run.sh" --background
Restart=on-failure
RestartSec=10
TimeoutStartSec=150
TimeoutStopSec=20

[Install]
WantedBy=graphical-session.target
UNIT
systemd-analyze --user verify "$unit"
systemctl --user daemon-reload
systemctl --user enable clove.service
if [ "${1:-}" = --now ]; then systemctl --user restart clove.service; echo "CLOVE is running as a service."
else echo "Installed: CLOVE starts with your next login. Start it now with: systemctl --user start clove"; fi

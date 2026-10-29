#!/usr/bin/env bash
# Starts CLOVE with your graphical session, no terminal needed: a systemd user service, `clove`.
#   scripts/install_autostart.sh            install and enable it (it starts at the next login)
#   scripts/install_autostart.sh --now      ...and start it now (stop a terminal-started CLOVE first)
#   scripts/install_autostart.sh --remove   disable and remove it
# Logs: ~/.local/state/clove/clove.log and stderr.log, plus `journalctl --user -u clove`.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)"
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

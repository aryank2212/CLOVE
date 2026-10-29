#!/usr/bin/env bash
# Starts Clove. Logs: ~/.local/state/clove/clove.log. Crash output goes to the journal under the login service
# (journalctl --user -u clove), else to stderr.log there.
cd "$(dirname "$0")" || exit 1
if [ -t 1 ] || [ -n "${INVOCATION_ID:-}" ]; then exec .venv/bin/python agent.py "$@"; fi
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/clove"
exec .venv/bin/python agent.py "$@" 2>> "${XDG_STATE_HOME:-$HOME/.local/state}/clove/stderr.log" >/dev/null

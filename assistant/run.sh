#!/usr/bin/env bash
# Starts Clove. Logs: ~/.local/state/clove/clove.log. Crash output goes to the journal under the login service
# (journalctl --user -u clove), else to stderr.log there.
cd "$(dirname "$0")" || exit 1
# A broken Python environment (the Python it was built with was upgraded or removed) used to fail silently: say so, once
# per ten minutes, with a desktop notification, instead of crashing and being restarted in the dark.
if ! .venv/bin/python -c "import dotenv, google.genai, numpy" 2>/dev/null; then
  state="${XDG_STATE_HOME:-$HOME/.local/state}/clove"; mkdir -p "$state"
  msg="CLOVE can't start: its Python environment no longer works (the Python it was built with changed). Point .venv at the Python it was made with, or rebuild it: see docs/GUIDE.md, 'If CLOVE won't start'."
  echo "$msg" >&2
  if command -v notify-send >/dev/null && [ -z "$(find "$state/.notified-env" -mmin -10 2>/dev/null)" ]; then
    touch "$state/.notified-env"; notify-send -u critical "CLOVE didn't start" "$msg"
  fi
  exit 1
fi
if [ -t 1 ] || [ -n "${INVOCATION_ID:-}" ]; then exec .venv/bin/python agent.py "$@"; fi
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/clove"
exec .venv/bin/python agent.py "$@" 2>> "${XDG_STATE_HOME:-$HOME/.local/state}/clove/stderr.log" >/dev/null

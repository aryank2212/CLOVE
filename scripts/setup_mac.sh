#!/usr/bin/env bash
# One-time setup of CLOVE on a Mac (Apple silicon or Intel, macOS 13 or newer):
#   scripts/setup_mac.sh            Python environment, call audio devices, Chrome check
#   scripts/setup_mac.sh --local    ...and the local Qwen brain (Ollama, about 6 GB)
# Then: put GEMINI_API_KEY in .env, ./install_extension.sh, ./run.sh (and scripts/install_autostart.sh --now).
set -euo pipefail
[ "$(uname)" = Darwin ] || { echo "This script is for macOS." >&2; exit 1; }
dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$dir"

if ! command -v brew >/dev/null; then
  echo "Homebrew is needed (installs, Ollama, call audio). Install it from https://brew.sh, then run this again." >&2
  exit 1
fi

echo "==> Python"
py=""
for v in 3.13 3.12 3.11; do command -v "python$v" >/dev/null && { py="python$v"; break; }; done
if [ -z "$py" ]; then brew install python@3.12; py="$(brew --prefix)/bin/python3.12"; fi
[ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(sys.platform != "darwin")' 2>/dev/null && {
  echo "    .venv was made on another system; making a new one"; rm -rf .venv; }
[ -x .venv/bin/python ] || "$py" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Call audio (two BlackHole virtual devices; macOS asks for your password once)"
for cask in blackhole-2ch blackhole-16ch; do brew list --cask "$cask" >/dev/null 2>&1 || brew install --cask "$cask"; done

echo "==> Google Chrome"
if [ -d "/Applications/Google Chrome.app" ] || [ -d "$HOME/Applications/Google Chrome.app" ]; then echo "    found"
else echo "    not found: brew install --cask google-chrome (CLOVE drives Chrome through its extension)"; fi

[ -f .env ] || { cp .env.example .env; echo "==> Made .env from .env.example: put your GEMINI_API_KEY in it"; }

if [ "${1:-}" = --local ]; then scripts/install_local.sh; fi

cat <<MSG

Done. Next:
  1. GEMINI_API_KEY in .env
  2. ./install_extension.sh          (load the Chrome extension once)
  3. ./run.sh                        (macOS asks for the Microphone the first time)
  4. In System Settings > Privacy & Security, turn on for Terminal (and for $dir/.venv/bin/python
     if you use the login agent):
       - Accessibility                         window control, dictation typing, media keys
       - Screen & System Audio Recording       "what's on my screen", pointing
  5. scripts/install_autostart.sh --now   (start with every login)
  ./run.sh --doctor checks all of it.
MSG

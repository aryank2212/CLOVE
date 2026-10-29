#!/usr/bin/env bash
# CLOVE installer. Run it from the CLOVE folder:  ./install.sh
# It sets up the assistant (a Python environment and your settings), then offers the login service, the Chrome
# extension and the CLOVE island. Nothing needs root except installing missing system packages, which it only
# suggests. Safe to run again: it keeps your settings and skips what is already done.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
app="$here/assistant"
bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask() { local a; read -r -p "  $1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[Yy] ]]; }

[ "$(uname -s)" = Linux ] || { echo "CLOVE runs on Linux only."; exit 1; }

bold "1. Checking this PC"
missing=()
py=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then py="$c"; break; fi
done
[ -n "$py" ] && ok "Python: $("$py" --version)" || missing+=("python (3.11 or newer)")
for tool in pactl wtype wl-copy grim; do
  command -v "$tool" >/dev/null && ok "$tool" || warn "$tool not found (some features need it)"
done
command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null || command -v chromium >/dev/null \
  && ok "Chrome or Chromium" || warn "No Chrome or Chromium: CLOVE can't control the web without one"
if [ ${#missing[@]} -gt 0 ]; then
  echo; echo "  Install first: ${missing[*]}"
  if command -v pacman >/dev/null; then echo "  e.g.  sudo pacman -S python"
  elif command -v apt-get >/dev/null; then echo "  e.g.  sudo apt install python3 python3-venv"
  elif command -v dnf >/dev/null; then echo "  e.g.  sudo dnf install python3"; fi
  exit 1
fi

bold "2. Setting up the assistant"
if [ ! -x "$app/.venv/bin/python" ]; then
  "$py" -m venv "$app/.venv"
fi
"$app/.venv/bin/python" -m pip install --quiet --upgrade pip
echo "  Installing Python packages (a few minutes the first time)…"
"$app/.venv/bin/python" -m pip install --quiet -r "$app/requirements.txt"
ok "Python packages installed"

env="$app/.env"
if [ ! -f "$env" ]; then
  cp "$app/.env.example" "$env"
  chmod 600 "$env"
  read -r -p "  Your first name (how CLOVE addresses you, Enter to skip): " name
  [ -n "$name" ] && sed -i "s/^USER_NAME=.*/USER_NAME=${name//[^A-Za-z -]/}/" "$env"
  echo "  CLOVE thinks with Google's Gemini. A free key: https://aistudio.google.com/apikey"
  read -r -s -p "  Paste your Gemini API key (hidden, Enter to skip and use the local brain only): " key; echo
  if [ -n "$key" ]; then
    if grep -q "^GEMINI_API_KEY=" "$env"; then sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${key//[^A-Za-z0-9_-]/}|" "$env"
    else printf 'GEMINI_API_KEY=%s\n' "${key//[^A-Za-z0-9_-]/}" >> "$env"; fi
    ok "Key saved to assistant/.env (only you can read that file)"
  else
    warn "No key: add GEMINI_API_KEY to assistant/.env later, or install the local brain (step 6)"
  fi
else
  ok "Settings kept: assistant/.env"
fi

bold "3. Start with your session"
if ask "Start CLOVE automatically when you log in (a systemd user service)?"; then
  "$app/scripts/install_autostart.sh"
fi

bold "4. Chrome extension (lets CLOVE use the web for you)"
if ask "Open Chrome's extension page now to add it (two clicks)?"; then
  "$app/install_extension.sh" || warn "Could not open Chrome; run assistant/install_extension.sh later"
fi

bold "5. The CLOVE island (the notch at the top of the screen, and the CLOVE app)"
if command -v cargo >/dev/null && command -v npm >/dev/null; then
  if ask "Build and install the island now (about 10 minutes the first time)?"; then
    (cd "$here/island" && npm install --no-audit --no-fund && npx tauri build --no-bundle)
    mkdir -p "$HOME/.local/bin"
    install -m755 "$here/island/target/release/clove-island" "$HOME/.local/bin/clove-island"
    install -m755 "$here/island/target/release/clove-island-hook" "$HOME/.local/bin/clove-island-hook"
    ok "Installed to ~/.local/bin. Start it with:  clove-island"
  fi
else
  warn "Building the island needs Rust (cargo) and Node.js (npm). Install them, then run ./install.sh again."
fi

bold "6. Optional: the local brain (private, offline; needs an NVIDIA GPU with 8 GB)"
echo "  Run later if you want it:  assistant/scripts/install_local.sh"

bold "Checking everything"
(cd "$app" && ./run.sh --doctor) || true

bold "Done"
if systemctl --user is-enabled clove.service >/dev/null 2>&1; then
  echo "  Start CLOVE now:  systemctl --user start clove     (from now on it starts when you log in)"
else
  echo "  Start CLOVE:  $app/run.sh"
fi
echo "  Then say \"Clove\", and ask it something."

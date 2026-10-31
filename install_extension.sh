#!/usr/bin/env bash
# One-time: put the Clove Hands extension into Chrome (or Edge: ./install_extension.sh edge).
# Chrome never lets a program install an unpacked extension silently, so this opens the page and copies the folder path.
dir="$(cd "$(dirname "$0")" && pwd)/chrome_extension"
if [ "$(uname)" = Darwin ]; then
  printf %s "$dir" | pbcopy
  if [ "$1" = edge ]; then app="Microsoft Edge"; page="edge://extensions"; else app="Google Chrome"; page="chrome://extensions"; fi
  exe="/Applications/$app.app/Contents/MacOS/$app"
  if [ -x "$exe" ]; then nohup "$exe" "$page" >/dev/null 2>&1 & else open -a "$app"; echo "Type $page in the address bar."; fi
else
  if command -v wl-copy >/dev/null; then printf %s "$dir" | wl-copy; elif command -v xclip >/dev/null; then printf %s "$dir" | xclip -selection clipboard; fi
  if [ "$1" = edge ]; then nohup microsoft-edge "edge://extensions" >/dev/null 2>&1 & else nohup google-chrome "chrome://extensions" >/dev/null 2>&1 & fi
fi
cat <<MSG
In the page that just opened:
  1. Turn on "Developer mode" (top right)
  2. Click "Load unpacked"
  3. Choose this folder (path is on your clipboard, or type it):  $dir
The extension icon then shows "ON" whenever Clove is running.
MSG

"""Presence lock: Bluetooth disconnect -> lock screen, pause media, save state."""
import asyncio
import logging
import subprocess

log = logging.getLogger("clove.presence_lock")

def _connected_phones() -> int:
    out = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True, text=True, timeout=6).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])

async def monitor(on_away, on_back, poll: float = 5.0):
    was_away = False
    while True:
        try:
            away = _connected_phones() == 0
            if away and not was_away:
                was_away = True
                await on_away()
            elif not away and was_away:
                was_away = False
                await on_back()
        except Exception as e:
            log.warning("presence error: %s", e)
        await asyncio.sleep(poll)

def lock_screen() -> str:
    subprocess.run(["loginctl", "lock-session"], capture_output=True, timeout=5)
    return "screen locked"

def pause_media() -> str:
    subprocess.run(["playerctl", "pause"], capture_output=True, timeout=5)
    return "media paused"

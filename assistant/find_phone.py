"""Find my phone: ring via Bluetooth or Telegram."""
import subprocess
import logging

log = logging.getLogger("clove.find_phone")

def ring_bluetooth() -> str:
    # Use findmyphone-style: play a loud tone via the phone? Not directly.
    # Fallback: send a Telegram message + try bluetoothctl.
    return "Ring via Bluetooth not supported directly; sending Telegram ping."

def ping_telegram() -> str:
    from anton_bridge import text_me
    return text_me("Clove: find my phone — ring ring! Reply to stop.")

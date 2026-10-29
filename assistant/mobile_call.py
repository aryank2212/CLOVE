"""Mobile (Bluetooth HFP) call bridge for Clove.

Pairs with a phone over Bluetooth HFP so call audio routes through the PC.
Clove can auto-answer, listen via STT, reply via TTS, and hang up. Requires
the phone to be paired and the HFP profile active (PipeWire bluez).

Control uses `bluetoothctl` (answer/hangup/list-calls), which is available.
"""
import asyncio
import logging
import re
import subprocess
import time

log = logging.getLogger("clove.mobile_call")

AUTO_ANSWER = False


def _bt(*args) -> str:
    try:
        return subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception as e:
        return f"error: {e}"


def _hfp_devices() -> list[str]:
    out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=6).stdout
    return [ln.split()[1] for ln in out.splitlines() if "bluez" in ln.lower() and "input" in ln.lower()]


def _hfp_sinks() -> list[str]:
    out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=6).stdout
    return [ln.split()[1] for ln in out.splitlines() if "bluez" in ln.lower()]


def paired_phones() -> list[str]:
    out = _bt("devices", "Paired")
    return [ln for ln in out.splitlines() if ln.strip()]


import re as _re
def _strip_ansi(t): return _re.sub(r"\x1b\[[0-9;]*m", "", t)

def list_calls() -> list[str]:
    out = _strip_ansi(_bt("list-calls"))
    return [ln for ln in out.splitlines() if ln.strip() and "invalid" not in ln.lower() and "menu" not in ln.lower() and "help" not in ln.lower()]


async def monitor_calls(on_incoming, poll: float = 2.0):
    """Poll bluetoothctl for incoming calls; invoke on_incoming(call_id) when one appears."""
    seen = set()
    while True:
        try:
            for ln in list_calls():
                if "incoming" in ln.lower() or "ringing" in ln.lower():
                    cid = ln.split()[0] if ln.split() else ln
                    if cid not in seen:
                        seen.add(cid)
                        await on_incoming(cid)
        except Exception as e:
            log.warning("mobile monitor error: %s", e)
        await asyncio.sleep(poll)


def answer(call_id: str = "") -> str:
    return _bt("answer", call_id) if call_id else _bt("answer")


def hangup(call_id: str = "") -> str:
    return _bt("hangup", call_id) if call_id else _bt("hangup")


def hangup_all() -> str:
    return _bt("hangup-all")


def status() -> str:
    phones = paired_phones()
    srcs = _hfp_devices()
    sinks = _hfp_sinks()
    calls = list_calls()
    return ("Mobile calls:\n"
            f"  paired phones: {len(phones)}\n"
            f"  HFP sources: {srcs or 'none'}\n"
            f"  HFP sinks: {sinks or 'none'}\n"
            f"  active calls: {calls or 'none'}\n"
            f"  auto-answer: {AUTO_ANSWER}")


def set_auto_answer(on: bool) -> str:
    global AUTO_ANSWER
    AUTO_ANSWER = on
    return f"auto-answer {'ON' if on else 'OFF'}"


def pair_instructions() -> str:
    return ("Pair your phone: (1) put phone in pairing mode, (2) run `bluetoothctl`, "
            "(3) `scan on`, (4) `pair <MAC>`, (5) `trust <MAC>`, (6) `connect <MAC>`. "
            "Then enable HFP on the phone. Run `mobile_call_status` to verify.")

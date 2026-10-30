"""His phone's normal (cellular) calls, through Bluetooth: the PC is his phone's hands-free kit, like a car.

PipeWire (1.4+) speaks the hands-free protocol itself and offers the calls on the session bus as org.pipewire.Telephony,
with the oFono interfaces (VoiceCall: State, LineIdentification, Name; Answer, Hangup). The call's sound is a
Bluetooth source (the caller) and sink (what the caller hears), which PhoneAudio joins to the same two devices the
call agent already uses for Chrome calls, so the agent itself doesn't change.

Needs: Bluetooth on, and his phone paired with this PC and connected (on an iPhone: Settings › Bluetooth). It
works while the phone is in Bluetooth range of the PC.
"""
import json
import logging
import subprocess

from call_audio import FROM_CALL, TO_CALL, CallAudio, _json, _pactl

log = logging.getLogger("clove.cell")
SERVICE, ROOT = "org.pipewire.Telephony", "/org/pipewire/Telephony"
CALL = "org.ofono.VoiceCall"


def _busctl(*args: str, timeout: float = 6) -> str:
    try:
        return subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _value(v):
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def calls(raw: str | None = None) -> list[dict]:
    """Every call the phone has now: [{path, state, number, name}]. State: incoming, waiting, dialing, alerting,
    active, held, disconnected."""
    raw = raw if raw is not None else _busctl("call", SERVICE, ROOT, "org.freedesktop.DBus.ObjectManager",
                                              "GetManagedObjects", "--json=short")
    try:
        objects = json.loads(raw)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return []
    out = []
    for path, ifaces in objects.items():
        props = ifaces.get(CALL)
        if props is None:
            continue
        p = {k: _value(v) for k, v in props.items()}
        out.append({"path": path, "state": str(p.get("State", "")), "number": str(p.get("LineIdentification", "")),
                    "name": str(p.get("Name", ""))})
    return out


def ringing(raw: str | None = None) -> dict | None:
    return next((c for c in calls(raw) if c["state"] == "incoming"), None)


def state(path: str, raw: str | None = None) -> str:
    """The call's state, or "gone" once the phone dropped it."""
    return next((c["state"] for c in calls(raw) if c["path"] == path), "gone")


def answer(path: str) -> bool:
    r = subprocess.run(["busctl", "--user", "call", SERVICE, path, CALL, "Answer"], capture_output=True, text=True,
                       timeout=8)
    if r.returncode != 0:
        log.warning("could not answer %s: %s", path, r.stderr.strip()[:160])
    return r.returncode == 0


def hangup(path: str) -> bool:
    r = subprocess.run(["busctl", "--user", "call", SERVICE, path, CALL, "Hangup"], capture_output=True, text=True,
                       timeout=8)
    return r.returncode == 0


def bluetooth_nodes() -> tuple[str, str]:
    """(source, sink) of the phone's call audio: the Bluetooth hands-free devices PipeWire made for it."""
    src = next((s["name"] for s in _json("list", "sources")
                if s["name"].startswith("bluez_input.") and not s["name"].endswith(".monitor")), "")
    sink = next((s["name"] for s in _json("list", "sinks") if s["name"].startswith("bluez_output.")), "")
    return src, sink


class PhoneAudio(CallAudio):
    """CallAudio for a phone call over Bluetooth: no browser streams to move, just four loops.

        the caller (Bluetooth source)  ->  clove_from_call   (the agent listens)
        clove_to_call's monitor (the agent's voice)  ->  the Bluetooth sink  (the caller hears it)
        and both looped to his speakers, as for Chrome calls."""

    def setup(self, attach: bool = False):
        self.teardown_leftovers()
        src, sink = bluetooth_nodes()
        if not src or not sink:
            raise RuntimeError("the phone's call audio isn't on this PC (is the phone connected over Bluetooth?)")
        for args in (
            ("module-null-sink", f"sink_name={TO_CALL}", "sink_properties=device.description=Clove_voice_into_call"),
            ("module-null-sink", f"sink_name={FROM_CALL}", "sink_properties=device.description=Sound_from_call_to_Clove"),
            ("module-loopback", f"source={src}", f"sink={FROM_CALL}", "latency_msec=40"),
            ("module-loopback", f"source={TO_CALL}.monitor", f"sink={sink}", "latency_msec=40"),
        ):
            out = _pactl("load-module", *args)
            if not out.isdigit():
                self.teardown()
                raise RuntimeError(f"could not connect the phone's call audio ({args[0]})")
            self.modules.append(out)
        if self.loop_to_speakers:
            for s in (FROM_CALL, TO_CALL):
                out = _pactl("load-module", "module-loopback", f"source={s}.monitor", f"sink={self.speaker_sink}",
                             "latency_msec=50")
                if out.isdigit():
                    self.modules.append(out)
        self.sink, self.owner_loop = sink, ""
        self.moved_in = {0: "bluetooth"}          # "the call's sound is routed" (the agent's no-sound check counts it)
        self.active = True
        log.info("phone call audio ready (%s -> agent -> %s)", src, sink)

    def route_once(self) -> tuple[int, int]:
        return 1, 1

    def adopt_all(self):
        return 1, 1

    def give_back_streams(self):
        self.moved_in.clear()

    def hand_mic_to_owner(self, on: bool):
        """He talks himself: his microphone goes to the caller too; off again when he hands back."""
        self.owner_mic = on
        if on and not self.owner_loop:
            out = _pactl("load-module", "module-loopback", "source=@DEFAULT_SOURCE@", f"sink={self.sink}",
                         "latency_msec=40")
            if out.isdigit():
                self.owner_loop = out
                self.modules.append(out)
        elif not on and self.owner_loop:
            _pactl("unload-module", self.owner_loop)
            if self.owner_loop in self.modules:
                self.modules.remove(self.owner_loop)
            self.owner_loop = ""

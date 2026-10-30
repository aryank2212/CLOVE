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
import threading
import time

from call_audio import FROM_CALL, TO_CALL, CallAudio, _json, _pactl

log = logging.getLogger("clove.cell")
SERVICE, ROOT = "org.pipewire.Telephony", "/org/pipewire/Telephony"
CALL = "org.ofono.VoiceCall"
CALL_NATIVE = "org.pipewire.Telephony.Call1"
GATEWAY = "org.pipewire.Telephony.AudioGateway1"


def _busctl(*args: str, timeout: float = 6) -> str:
    try:
        return subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _value(v):
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def _data(raw: str):
    try:
        return json.loads(raw)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return {}


def gateways(raw: str | None = None) -> list[str]:
    """The phones connected now (one "audio gateway" each)."""
    raw = raw if raw is not None else _busctl("call", SERVICE, ROOT, "org.freedesktop.DBus.ObjectManager",
                                              "GetManagedObjects", "--json=short")
    return [path for path, ifaces in _data(raw).items() if GATEWAY in ifaces or "org.ofono.VoiceCallManager" in ifaces]


def calls(raw: dict[str, str] | None = None) -> list[dict]:
    """Every call the connected phones have now: [{path, state, number, name}]. State: incoming, waiting, dialing,
    alerting, active, held, disconnected. raw: {gateway path: GetCalls json} (tests)."""
    if raw is None:
        raw = {gw: _busctl("call", SERVICE, gw, "org.ofono.VoiceCallManager", "GetCalls", "--json=short")
               for gw in gateways()}
    out = []
    for text in raw.values():
        for path, props in _data(text).items():
            p = {k: _value(v) for k, v in props.items()}
            out.append({"path": path, "state": str(p.get("State", "")),
                        "number": str(p.get("LineIdentification", "")), "name": str(p.get("Name", ""))})
    return out


def ringing(raw: dict[str, str] | None = None) -> dict | None:
    return next((c for c in calls(raw) if c["state"] == "incoming"), None)


def state(path: str, raw: dict[str, str] | None = None) -> str:
    """The call's state, or "gone" once the phone dropped it."""
    return next((c["state"] for c in calls(raw) if c["path"] == path), "gone")


def _call_method(path: str, method: str) -> bool:
    """The oFono interface first, PipeWire's own if that one isn't there."""
    err = ""
    for iface in (CALL, CALL_NATIVE):
        r = subprocess.run(["busctl", "--user", "call", SERVICE, path, iface, method], capture_output=True, text=True,
                           timeout=8)
        if r.returncode == 0:
            return True
        err = r.stderr.strip()[:160]
    log.warning("could not %s %s: %s", method.lower(), path, err)
    return False


def answer(path: str) -> bool:
    return _call_method(path, "Answer")


def hangup(path: str) -> bool:
    return _call_method(path, "Hangup")


def address_of(call_path: str, raw: str | None = None) -> str:
    """The Bluetooth address of the phone a call belongs to (its gateway is the call path's parent)."""
    gateway = call_path.rsplit("/", 1)[0]
    raw = raw if raw is not None else _busctl("call", SERVICE, ROOT, "org.freedesktop.DBus.ObjectManager",
                                              "GetManagedObjects", "--json=short")
    props = _data(raw).get(gateway, {}).get(GATEWAY, {})
    return str(_value(props.get("Address", "")) or "")


def bluetooth_nodes(address: str = "") -> tuple[str, str]:
    """(source, sink) of the phone's call audio: the Bluetooth hands-free devices PipeWire made for it. With the
    phone's address, only its own (never earbuds that are connected too)."""
    tag = address.replace(":", "_").upper()
    mine = (lambda n: tag in n.upper()) if tag else (lambda n: True)
    src = next((s["name"] for s in _json("list", "sources") if s["name"].startswith("bluez_input.")
                and not s["name"].endswith(".monitor") and mine(s["name"])), "")
    sink = next((s["name"] for s in _json("list", "sinks") if s["name"].startswith("bluez_output.") and mine(s["name"])), "")
    return src, sink


def links(text: str | None = None) -> list[tuple[str, str]]:
    """Every audio link as (output port, input port), from `pw-link -l`."""
    if text is None:
        try:
            text = subprocess.run(["pw-link", "-l"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    out, port = [], ""
    for line in text.splitlines():
        if not line.startswith(" "):
            port = line.strip()
        elif "|->" in line:
            out.append((port, line.split("|->", 1)[1].strip()))
    return out


def direct_links(pairs: list[tuple[str, str]], tag: str) -> list[tuple[str, str]]:
    """Links joining the phone straight to the PC's own microphone or speakers (what a car kit does): while CLOVE
    is on the call they let the caller hear the room and the room hear the caller, past CLOVE."""
    def phone(p):
        return p.startswith(("bluez_input.", "bluez_output.")) and (not tag or tag in p.upper())

    def device(p):
        return p.startswith(("alsa_input.", "alsa_output."))
    return [(o, i) for o, i in pairs if (phone(o) and device(i)) or (device(o) and phone(i))]


class PhoneAudio(CallAudio):
    """CallAudio for a phone call over Bluetooth: no browser streams to move, just four loops.

        the caller (Bluetooth source)  ->  clove_from_call   (the agent listens)
        clove_to_call's monitor (the agent's voice)  ->  the Bluetooth sink  (the caller hears it)
        and both looped to his speakers, as for Chrome calls."""

    address = ""                                  # the phone's Bluetooth address, set before setup

    def setup(self, attach: bool = False):
        self.teardown_leftovers()
        src, sink = bluetooth_nodes(self.address)
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
        log.info("phone call audio ready (%s -> agent -> %s); links: %s", src, sink,
                 [p for p in links() if "bluez" in p[0] or "bluez" in p[1]])
        self._watch = threading.Thread(target=self._keep_apart, daemon=True)
        self._watch.start()

    def _keep_apart(self):
        """The desktop links a phone call to the speakers and microphone by itself, and may do it again: undo it
        while CLOVE has the call (not while he talks himself)."""
        tag = self.address.replace(":", "_").upper()
        while self.active:
            if not self.owner_mic:
                for o, i in direct_links(links(), tag):
                    subprocess.run(["pw-link", "-d", o, i], capture_output=True, timeout=5)
                    log.info("phone call: unlinked %s -> %s", o, i)
            time.sleep(1)

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

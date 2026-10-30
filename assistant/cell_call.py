"""His phone's normal (cellular) calls, through Bluetooth: the PC is his phone's hands-free kit, like a car.

PipeWire (1.4+) speaks the hands-free protocol itself and offers the calls on the session bus as org.pipewire.Telephony,
with the oFono interfaces (VoiceCall: State, LineIdentification, Name; Answer, Hangup). The call's sound only comes
to the PC once asked for (AudioGatewayTransport1.Activate), as two streams: the caller (playing) and what the caller
hears (recording). PhoneAudio moves them to the same two devices the call agent uses for Chrome calls, so the agent
itself doesn't change.

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


TRANSPORT = "org.pipewire.Telephony.AudioGatewayTransport1"


def open_audio(call_path: str) -> bool:
    """Ask the phone to send the call's sound to the PC. A hands-free kit must ask for it (the phone keeps it
    otherwise, and the PC shows no Bluetooth audio at all)."""
    gateway = call_path.rsplit("/", 1)[0]
    r = subprocess.run(["busctl", "--user", "call", SERVICE, gateway, TRANSPORT, "Activate"], capture_output=True,
                       text=True, timeout=8)
    if r.returncode != 0:
        log.info("asking for the call's audio: %s", r.stderr.strip()[:160])
    return r.returncode == 0


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


def bluetooth_nodes(address: str = "") -> tuple[int | None, int | None]:
    """The phone's call audio, as PipeWire makes it for a hands-free kit: two STREAMS (like an app's), not devices.
    (caller -> PC: a playback stream, a "sink input"; PC -> caller: a recording stream, a "source output").
    Returns their indexes, or None. With the phone's address, only its own (never earbuds connected too)."""
    tag = address.replace(":", "_").upper()

    def mine(item, prefix):
        name = str((item.get("properties") or {}).get("node.name", ""))
        return name.startswith(prefix) and (not tag or tag in name.upper())
    caller = next((s["index"] for s in _json("list", "sink-inputs") if mine(s, "bluez_input.")), None)
    to_phone = next((s["index"] for s in _json("list", "source-outputs") if mine(s, "bluez_output.")), None)
    return caller, to_phone


class PhoneAudio(CallAudio):
    """CallAudio for a phone call over Bluetooth. The call's two streams are moved like a Chrome call's:

        the caller (playback stream)  ->  clove_from_call   (the agent listens; looped to his speakers)
        clove_to_call's monitor (the agent's voice)  ->  the phone's recording stream  (the caller hears it)

    Left alone, the desktop plays the caller on his speakers and records his room into the call."""

    address = ""                                  # the phone's Bluetooth address, set before setup

    def setup(self, attach: bool = False):
        self.teardown_leftovers()
        caller, to_phone = bluetooth_nodes(self.address)
        if caller is None or to_phone is None:
            raise RuntimeError("the phone's call audio isn't on this PC (is the phone connected over Bluetooth?)")
        for args in (
            ("module-null-sink", f"sink_name={TO_CALL}", "sink_properties=device.description=Clove_voice_into_call"),
            ("module-null-sink", f"sink_name={FROM_CALL}", "sink_properties=device.description=Sound_from_call_to_Clove"),
        ):
            out = _pactl("load-module", *args)
            if not out.isdigit():
                self.teardown()
                raise RuntimeError(f"could not create the virtual audio device ({args[0]})")
            self.modules.append(out)
        if self.loop_to_speakers:                 # he hears both sides, as for Chrome calls
            for src in (FROM_CALL, TO_CALL):
                out = _pactl("load-module", "module-loopback", f"source={src}.monitor", f"sink={self.speaker_sink}",
                             "latency_msec=50")
                if out.isdigit():
                    self.modules.append(out)
        self.active = True
        self.route_once()
        log.info("phone call audio ready (caller stream %s -> agent, agent -> phone stream %s)", caller, to_phone)
        self._watch = threading.Thread(target=self._keep_routed, daemon=True)
        self._watch.start()

    def route_once(self) -> tuple[int, int]:
        """The caller into clove_from_call; the phone's recording from CLOVE's voice (or his microphone, while he
        has taken over). Remembers where they were, to put them back."""
        if not self.active:
            return 0, 0
        caller, to_phone = bluetooth_nodes(self.address)
        sinks = {s["index"]: s["name"] for s in _json("list", "sinks")}
        sources = {s["index"]: s["name"] for s in _json("list", "sources")}
        n_in = n_out = 0
        if caller is not None:
            si = next((x for x in _json("list", "sink-inputs") if x["index"] == caller), {})
            if sinks.get(si.get("sink")) != FROM_CALL:
                self.moved_in.setdefault(caller, sinks.get(si.get("sink"), "@DEFAULT_SINK@"))
                _pactl("move-sink-input", str(caller), FROM_CALL)
            n_in = 1
        if to_phone is not None:
            want = "@DEFAULT_SOURCE@" if self.owner_mic else f"{TO_CALL}.monitor"
            so = next((x for x in _json("list", "source-outputs") if x["index"] == to_phone), {})
            now = sources.get(so.get("source"))
            if (self.owner_mic and now in (f"{TO_CALL}.monitor", None)) or (not self.owner_mic and now != f"{TO_CALL}.monitor"):
                self.moved_out.setdefault(to_phone, now or "@DEFAULT_SOURCE@")
                _pactl("move-source-output", str(to_phone), want)
            n_out = 1
        return n_in, n_out

    def _keep_routed(self):
        while self.active:                        # the desktop may put them back on the speakers and microphone
            self.route_once()
            time.sleep(1)

    def adopt_all(self):
        return self.route_once()

    def hand_mic_to_owner(self, on: bool):
        """He talks himself: the phone records his microphone; back to CLOVE's voice when he hands back."""
        self.owner_mic = on
        self.route_once()

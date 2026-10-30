"""His phone's normal calls over Bluetooth (PipeWire's org.pipewire.Telephony): reading the calls, which one is ringing,
answering it, and joining the Bluetooth call audio to the agent's devices. The bus and pactl are stand-ins."""
import asyncio
import json
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cell_call  # noqa: E402
import call_watch as CW  # noqa: E402
import config  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


def objects(*calls):
    """{gateway: GetCalls json}, as the phone's line answers."""
    data = {}
    for i, (st, num, name) in enumerate(calls):
        data[f"/org/pipewire/Telephony/ag1/call{i}"] = {
            "State": {"type": "s", "data": st}, "LineIdentification": {"type": "s", "data": num},
            "Name": {"type": "s", "data": name}}
    return {"/org/pipewire/Telephony/ag1": json.dumps({"type": "a{oa{sv}}", "data": [data]})}


ROOT_REAL = json.dumps({"type": "a{oa{sa{sv}}}", "data": [{"/org/pipewire/Telephony/ag1": {
    "org.pipewire.Telephony.AudioGateway1": {"Address": {"type": "s", "data": "AC:00:7A:F2:F0:6C"}},
    "org.pipewire.Telephony.AudioGatewayTransport1": {"State": {"type": "s", "data": "idle"}}}}]})
check("the connected phone's line is found (as on this PC)", cell_call.gateways(ROOT_REAL) == ["/org/pipewire/Telephony/ag1"])
check("a call's phone address", cell_call.address_of("/org/pipewire/Telephony/ag1/call0", ROOT_REAL) == "AC:00:7A:F2:F0:6C")
check("no phone: no lines", cell_call.gateways(json.dumps({"type": "a{oa{sa{sv}}}", "data": [{}]})) == [])


# ---- reading the bus ------------------------------------------------------------------------------------
check("a line with no calls: no calls", cell_call.calls({"/ag1": json.dumps({"type": "a{oa{sv}}", "data": [{}]})}) == [])
check("garbage: no calls, no crash", cell_call.calls({"/ag1": "not json"}) == [])
raw = objects(("active", "+911234", "Mum"), ("incoming", "+919876", ""))
check("each call with its state and number", [c["state"] for c in cell_call.calls(raw)] == ["active", "incoming"])
r = cell_call.ringing(raw)
check("the ringing one is found (not the call he is on)", r and r["number"] == "+919876")
check("no ringing call: None", cell_call.ringing(objects(("active", "+911234", "Mum"))) is None)
check("a call's state", cell_call.state("/org/pipewire/Telephony/ag1/call0", raw) == "active")
check("a dropped call is gone", cell_call.state("/org/pipewire/Telephony/ag1/call9", raw) == "gone")

# ---- the audio: the call's two streams moved to the agent's devices ---------------------------------------
PHONE = "AC_00_7A_F2_F0_6C"
state_pa = {"si": {"index": 18651, "sink": 60, "properties": {"node.name": f"bluez_input.{PHONE}.0"}},
            "so": {"index": 18652, "source": 62, "properties": {"node.name": f"bluez_output.{PHONE}.1"}}}
SINKS = [{"index": 60, "name": "alsa_output.speakers"}, {"index": 70, "name": "clove_from_call"}]
SOURCES = [{"index": 62, "name": "alsa_input.mic"}, {"index": 71, "name": "clove_to_call.monitor"}]
earbuds = {"index": 900, "sink": 60, "properties": {"node.name": "bluez_input.08_E4_DF_2B_BE_75.0"}}
cmds = []


def fake_pactl(*a):
    cmds.append(a)
    if a[0] == "load-module":
        return str(len(cmds))
    if a[0] == "move-sink-input":
        state_pa["si"]["sink"] = next(x["index"] for x in SINKS if x["name"] == a[2])
    if a[0] == "move-source-output":
        name = {"@DEFAULT_SOURCE@": "alsa_input.mic"}.get(a[2], a[2])
        state_pa["so"]["source"] = next(x["index"] for x in SOURCES if x["name"] == name)
    return ""


cell_call._pactl = fake_pactl
cell_call._json = lambda *a: {"sink-inputs": [earbuds, state_pa["si"]], "source-outputs": [state_pa["so"]],
                              "sinks": SINKS, "sources": SOURCES}[a[1]]
cell_call.CallAudio.teardown_leftovers = staticmethod(lambda: None)
check("the call's streams are found, not the earbuds'", cell_call.bluetooth_nodes("AC:00:7A:F2:F0:6C") == (18651, 18652))
pa = cell_call.PhoneAudio(loop_to_speakers=True)
pa.address = "AC:00:7A:F2:F0:6C"
pa._keep_routed = lambda: None
pa.setup()
check("the caller goes to the agent, not the speakers", state_pa["si"]["sink"] == 70)
check("the quiet phone line is turned up", ("set-sink-input-volume", "18651", cell_call.CALLER_GAIN) in cmds)
check("the caller hears the agent, not the room", state_pa["so"]["source"] == 71)
check("he hears both sides", sum("sink=@DEFAULT_SINK@" in " ".join(c) for c in cmds) == 2)
check("the earbuds are never touched", earbuds["sink"] == 60)
pa.hand_mic_to_owner(True)
check("taking over: the caller hears his microphone", state_pa["so"]["source"] == 62)
pa.hand_mic_to_owner(False)
check("handing back: the agent again", state_pa["so"]["source"] == 71)
state_pa["si"]["sink"] = 60
pa.route_once()
check("moved back by the desktop: moved again", state_pa["si"]["sink"] == 70)
cell_call._json = lambda *a: []
try:
    cell_call.PhoneAudio().setup()
    check("no phone audio: a clear error", False)
except RuntimeError as e:
    check("no phone audio: a clear error", "Bluetooth" in str(e))


# ---- the watcher answers a ringing phone call -------------------------------------------------------------
class FakeCalls:
    def __init__(self):
        self.task, self.last_report, self.phone, self.whatsapp = None, "", [], []

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    async def start_phone(self, call, who, mission):
        self.phone.append((call, who, mission))
        self.task = asyncio.create_task(asyncio.sleep(0.1))
        return "Answering"

    async def start(self, *a, **k):
        self.whatsapp.append(a)
        return "Starting"


async def main():
    calls = FakeCalls()
    a = SimpleNamespace(dashboard=SimpleNamespace(prefs={"answercalls": True}), calls=calls,
                        messages=SimpleNamespace(recent=deque()))
    w = CW.CallWatch(a)
    config.CLOVE_TELEGRAM_BOT_TOKEN = ""
    cell_call.ringing = lambda raw=None: {"path": "/x/call1", "state": "incoming", "number": "+919876", "name": ""}
    await w.check()
    check("a ringing phone call is answered", len(calls.phone) == 1)
    check("named by its number when the phone gives no name", calls.phone[0][1] == "+919876")
    check("the brief says it's his phone", "on his phone" in calls.phone[0][2])
    await w.check()
    check("not answered twice", len(calls.phone) == 1)
    # a call he takes himself: the assistant stops listening, and listens again afterwards
    a.muted, calls.task = False, None
    w.phone_changed([{"path": "/ag1/call5", "state": "active", "number": "", "name": ""}])
    check("during a phone call CLOVE isn't on, the assistant doesn't listen", a.muted is True)
    w.phone_changed([])
    check("and listens again when it ends", a.muted is False)
    a.muted = True
    w.phone_changed([{"path": "/ag1/call6", "state": "active", "number": "", "name": ""}])
    w.phone_changed([])
    check("a mute he set himself stays", a.muted is True)

    a.dashboard.prefs["answercalls"] = False
    w.answered_at = 0
    await asyncio.sleep(0.2)
    await w.check()
    check("with the setting off the phone is left alone", len(calls.phone) == 1)


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

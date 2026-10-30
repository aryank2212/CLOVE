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

# ---- the audio: the Bluetooth call joined to the agent's two devices -------------------------------------
loaded = []
cell_call._pactl = lambda *a: (loaded.append(a), str(len(loaded)))[1] if a[0] == "load-module" else ""
cell_call._json = lambda *a: ([{"name": "bluez_input.08_E4_DF_2B_BE_75.0"}, {"name": "bluez_input.F4_43_D0_34_1E_EE.0"},
                               {"name": "alsa_input.mic"}] if a[1] == "sources"
                              else [{"name": "bluez_output.08_E4_DF_2B_BE_75.1"}, {"name": "bluez_output.F4_43_D0_34_1E_EE.1"},
                                    {"name": "alsa_output.speakers"}])
check("the phone's own call audio, not the earbuds'", cell_call.bluetooth_nodes("F4:43:D0:34:1E:EE")
      == ("bluez_input.F4_43_D0_34_1E_EE.0", "bluez_output.F4_43_D0_34_1E_EE.1"))
cell_call.CallAudio.teardown_leftovers = staticmethod(lambda: None)
real_links = cell_call.links
cell_call.links = lambda text=None: real_links(text) if text is not None else []   # never touch this PC's real links
pa = cell_call.PhoneAudio(loop_to_speakers=True)
pa.address = "F4:43:D0:34:1E:EE"
pa.setup()
flat = [" ".join(a) for a in loaded]
check("the caller's voice goes to the agent", any("source=bluez_input.F4_43_D0_34_1E_EE.0 sink=clove_from_call" in f for f in flat))
check("the agent's voice goes to the caller", any("source=clove_to_call.monitor sink=bluez_output.F4_43_D0_34_1E_EE.1" in f for f in flat))
check("he hears both sides", sum("sink=@DEFAULT_SINK@" in f for f in flat) == 2)
pa.hand_mic_to_owner(True)
check("taking over: his microphone goes to the caller", "source=@DEFAULT_SOURCE@ sink=bluez_output.F4_43_D0_34_1E_EE.1" in " ".join(loaded[-1]))
cell_call._json = lambda *a: []
try:
    cell_call.PhoneAudio().setup()
    check("no phone audio: a clear error", False)
except RuntimeError as e:
    check("no phone audio: a clear error", "Bluetooth" in str(e))


# ---- the phone is never linked straight to the room while CLOVE has the call ---------------------------------
PW = """alsa_input.pci-0000_06_00.6.HiFi__Mic1__source:capture_FL
  |-> bluez_output.AC_00_7A_F2_F0_6C.1:playback_MONO
bluez_input.AC_00_7A_F2_F0_6C.0:capture_MONO
  |-> alsa_output.pci-0000_06_00.6.HiFi__Headphones__sink:playback_FL
  |-> clove_from_call_loop:input_MONO
clove_to_call.monitor:monitor_MONO
  |-> bluez_output.AC_00_7A_F2_F0_6C.1:playback_MONO
bluez_input.08_E4_DF_2B_BE_75.0:capture_MONO
  |-> alsa_output.pci-0000_06_00.6.HiFi__Headphones__sink:playback_FL
"""
pairs = cell_call.links(PW)
check("pw-link's list is read", len(pairs) == 5)
cut = cell_call.direct_links(pairs, "AC_00_7A_F2_F0_6C")
check("the room's mic -> the phone, and the phone -> the speakers, are cut",
      sorted(o.split(":")[0] for o, _ in cut) == ["alsa_input.pci-0000_06_00.6.HiFi__Mic1__source", "bluez_input.AC_00_7A_F2_F0_6C.0"])
check("CLOVE's own links stay", not any("clove" in o or "clove" in i for o, i in cut))
check("other Bluetooth devices (earbuds) are left alone", not any("08_E4" in o for o, _ in cut))


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

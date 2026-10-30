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
    data = {"/org/pipewire/Telephony/ag0": {"org.ofono.Modem": {"Online": {"type": "b", "data": True}}}}
    for i, (st, num, name) in enumerate(calls):
        data[f"/org/pipewire/Telephony/ag0/call{i}"] = {"org.ofono.VoiceCall": {
            "State": {"type": "s", "data": st}, "LineIdentification": {"type": "s", "data": num},
            "Name": {"type": "s", "data": name}}}
    return json.dumps({"type": "a{oa{sa{sv}}}", "data": [data]})


# ---- reading the bus ------------------------------------------------------------------------------------
check("no phone connected: no calls", cell_call.calls(json.dumps({"type": "a{oa{sa{sv}}}", "data": [{}]})) == [])
check("garbage: no calls, no crash", cell_call.calls("not json") == [])
raw = objects(("active", "+911234", "Mum"), ("incoming", "+919876", ""))
check("each call with its state and number", [c["state"] for c in cell_call.calls(raw)] == ["active", "incoming"])
r = cell_call.ringing(raw)
check("the ringing one is found (not the call he is on)", r and r["number"] == "+919876")
check("no ringing call: None", cell_call.ringing(objects(("active", "+911234", "Mum"))) is None)
check("a call's state", cell_call.state("/org/pipewire/Telephony/ag0/call0", raw) == "active")
check("a dropped call is gone", cell_call.state("/org/pipewire/Telephony/ag0/call9", raw) == "gone")

# ---- the audio: the Bluetooth call joined to the agent's two devices -------------------------------------
loaded = []
cell_call._pactl = lambda *a: (loaded.append(a), str(len(loaded)))[1] if a[0] == "load-module" else ""
cell_call._json = lambda *a: ([{"name": "bluez_input.F4_43_D0_34_1E_EE.0"}, {"name": "alsa_input.mic"}] if a[1] == "sources"
                              else [{"name": "bluez_output.F4_43_D0_34_1E_EE.1"}, {"name": "alsa_output.speakers"}])
cell_call.CallAudio.teardown_leftovers = staticmethod(lambda: None)
pa = cell_call.PhoneAudio(loop_to_speakers=True)
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
    a.dashboard.prefs["answercalls"] = False
    w.answered_at = 0
    await asyncio.sleep(0.2)
    await w.check()
    check("with the setting off the phone is left alone", len(calls.phone) == 1)


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

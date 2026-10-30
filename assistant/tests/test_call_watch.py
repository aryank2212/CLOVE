"""Picking up his WhatsApp calls: only when the setting is on, only a ringing call, the caller named from WhatsApp's
notification, and the summary sent to CLOVE's own Telegram bot afterwards. Chrome and the call are stand-ins."""
import asyncio
import sys
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import browser_bridge  # noqa: E402
import call_watch as CW  # noqa: E402
import config  # noqa: E402
import notifications as N  # noqa: E402
import phone  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


state = {"phase": "none"}


async def fake_bridge(act, timeout=25, **kw):
    if act == "call_state":
        return f"phase: {state['phase']}; mic: on; platform: whatsapp; tab: 7"
    return "ok"


browser_bridge.bridge.call = fake_bridge
browser_bridge.bridge.ws = object()                      # "connected" (nothing is sent: call is replaced)
sent = []
phone.send = lambda text, token="": sent.append((text, token))


class FakeCalls:
    def __init__(self):
        self.started, self.task, self.last_report = [], None, ""

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    async def start(self, platform, who, mission, url="", incoming=False, mode=""):
        self.started.append((platform, who, mission, incoming))

        async def call():
            await asyncio.sleep(0.2)
            self.last_report = "Priya called about the project; she'd like a call back after 6."
        self.task = asyncio.create_task(call())
        return "Starting the whatsapp call"


async def main():
    prefs = {"answercalls": False}
    calls = FakeCalls()
    a = SimpleNamespace(dashboard=SimpleNamespace(prefs=prefs), calls=calls,
                        messages=SimpleNamespace(recent=deque()))
    w = CW.CallWatch(a)
    config.USER_NAME, config.CLOVE_TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "Sam", "clove-bot", "42"

    state["phase"] = "incoming"
    await w.check()
    check("with the setting off a ringing call is left alone", calls.started == [])

    prefs["answercalls"] = True
    state["phase"] = "none"
    await w.check()
    check("nothing ringing: nothing happens", calls.started == [])

    state["phase"] = "in_call"
    await w.check()
    check("a call he is already on is not touched", calls.started == [])

    state["phase"] = "incoming"
    a.messages.recent.append(N.Note("Google Chrome", "Priya", "Incoming voice call", "WhatsApp", at=time.time()))
    await w.check()
    check("a ringing call is answered", len(calls.started) == 1 and calls.started[0][3] is True)
    check("the caller is named from WhatsApp's notification", calls.started[0][1] == "Priya")
    mission = calls.started[0][2]
    check("the brief: take a message, keep talking if they want, never hang up first",
          "take" in mission.lower() and "keep the conversation going" in mission and "never be the one to end the call" in mission)
    check("and never money, codes or promises", "money" in mission and "codes" in mission and "promise" in mission)

    await w.check()
    check("not answered twice while the call runs", len(calls.started) == 1)

    await asyncio.sleep(2.6)
    check("afterwards the summary goes to Telegram", sent and "Priya" in sent[-1][0] and "call back after 6" in sent[-1][0])
    check("from CLOVE's own bot, never another program's", sent and sent[-1][1] == "clove-bot")

    w.answered_at = 0
    sent.clear()
    a.messages.recent.clear()
    config.CLOVE_TELEGRAM_BOT_TOKEN = ""
    await w.check()
    check("an unknown caller is still answered", calls.started[-1][1] == "the caller")
    await asyncio.sleep(2.6)
    check("without CLOVE's own bot nothing goes to Telegram", sent == [])


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

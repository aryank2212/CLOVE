"""The same message is never sent twice to the same chat (Gemini Live sometimes repeats a tool call)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import browser_bridge  # noqa: E402
import tools  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


calls = []


async def fake_call(act, timeout=25, **kw):
    calls.append((act, kw))
    if act == "wa_chat":
        return f'opened WhatsApp chat "{kw["name"]}"'
    if act == "wa_send":
        return f'sent: "{kw["text"]}"'
    return "ok"


browser_bridge.bridge.call = fake_call
tb = tools.Toolbox.__new__(tools.Toolbox)
tb.sends, tb.wa_open = {}, ""


async def main():
    await tb._browser({"action": "wa_chat", "name": "Aniket"})
    first = await tb._browser({"action": "wa_send", "text": "Hello Aniket, I am Clove."})
    again = await tb._browser({"action": "wa_send", "text": "Hello  Aniket, I am Clove."})
    check("the first send goes out", first.startswith("sent"))
    check("the same text to the same chat is not sent again", again.startswith("ALREADY SENT"))
    check("so WhatsApp got it once", sum(1 for c in calls if c[0] == "wa_send") == 1)
    other = await tb._browser({"action": "wa_send", "text": "And one more thing."})
    check("a different message still goes", other.startswith("sent"))
    await tb._browser({"action": "wa_chat", "name": "Priya"})
    to_priya = await tb._browser({"action": "wa_send", "text": "Hello Aniket, I am Clove."})
    check("the same text to another chat goes", to_priya.startswith("sent"))
    tools.RESEND_GUARD_S = 0
    later = await tb._browser({"action": "wa_send", "text": "And one more thing."})
    check("after the guard time it can be sent again", later.startswith("sent"))


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

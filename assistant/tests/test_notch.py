"""CLOVE on Clove Notch: the events Clove sends (one JSON line each, Clove Notch's hook format), approvals answered
on Clove Notch, a card withdrawn when he answers elsewhere, and silence when Clove Notch isn't running."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import notch  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    fails += not ok


def fake_assistant():
    calls = {"approval": [], "text": [], "caption": []}
    tools = SimpleNamespace(plan={"title": "Restart homepage", "steps": [{"text": "Restart homepage on Anton"}],
                                  "approval": "pending"})
    tools.set_approval = lambda ok, src: (calls["approval"].append((ok, src)), tools.plan.__setitem__("approval", "x"))

    async def send_text(t):
        calls["text"].append(t)
    a = SimpleNamespace(tools=tools, dashboard=None, caption=lambda *x, **k: calls["caption"].append(x), send_text=send_text)
    return a, calls


async def main():
    sock = Path(tempfile.mkdtemp()) / "clove-notch.sock"
    notch.SOCK = sock
    got, answer = [], {"word": "allow"}

    async def serve(r, w):
        line = json.loads((await r.readline()).decode())
        got.append(line)
        if line["hook_event_name"] == "PermissionRequest":
            if answer["word"]:
                await asyncio.sleep(0.05)
                w.write((answer["word"] + "\n").encode())
                await w.drain()
            else:
                await asyncio.sleep(1)                  # like Clove Notch: the card stays up until someone decides
        w.close()

    a, calls = fake_assistant()
    isl = notch.Notch(a)
    isl.prompt("restart homepage")                    # Clove Notch isn't running yet: nothing happens
    await asyncio.sleep(0.05)
    check("no notch -> no error, nothing sent", not got)

    server = await asyncio.start_unix_server(serve, path=str(sock))
    isl.prompt("how is anton doing?")
    isl.tool_start("Machine check", "Machine check anton")
    isl.tool_end("Machine check", True)
    isl.reply("Anton is fine, sir.")
    await asyncio.sleep(0.2)
    names = [e["hook_event_name"] for e in got]
    check("session starts first", names[:1] == ["SessionStart"], names)
    check("prompt, tool, result, reply in order",
          names[1:] == ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"], names)
    check("every event is CLOVE's own pill", all(e["clove_agent"] == "clove" and e["session_id"] == "clove" for e in got))
    check("the step reads 'tool · what'", got[2]["tool_name"] == "Machine check" and got[2]["tool_input"]["command"])
    check("the reply is the final line", got[4]["last_assistant_message"] == "Anton is fine, sir.")

    got.clear()
    isl.ask_approval(a.tools.plan)
    await asyncio.sleep(0.3)
    check("a pending plan becomes a permission card", got and got[0]["hook_event_name"] == "PermissionRequest")
    check("the card names the plan and its steps", "Restart homepage" in got[0]["tool_input"]["command"])
    check("Allow on Clove Notch approves the plan", calls["approval"] == [(True, "on Clove Notch")])
    check("the brain is told", calls["text"] and "approved the plan on Clove Notch" in calls["text"][0])

    a2, calls2 = fake_assistant()
    isl2 = notch.Notch(a2)
    isl2.started = True
    answer["word"] = "deny"
    isl2.ask_approval(a2.tools.plan)
    await asyncio.sleep(0.3)
    check("Deny on Clove Notch rejects it", calls2["approval"] == [(False, "on Clove Notch")])

    a3, calls3 = fake_assistant()
    isl3 = notch.Notch(a3)
    isl3.started = True
    answer["word"] = ""                                 # nobody clicks
    got.clear()
    isl3.ask_approval(a3.tools.plan)
    await asyncio.sleep(0.1)
    isl3.approval_settled()                             # he said yes by voice instead
    await asyncio.sleep(0.2)
    check("answering elsewhere withdraws the card", [e["hook_event_name"] for e in got] == ["PermissionRequest", "Interrupt"])
    check("...and Clove Notch can no longer decide", not calls3["approval"])
    # messages and calls, like a phone's notifications, each on its app's own pill
    got.clear()
    isl.notice("WhatsApp", "message", "Sam", "are you free tonight?")
    isl.notice("Phone", "ringing", "+911234567890")
    isl.notice("X", "replied", "Priya", "Hi, this is CLOVE.")
    await asyncio.sleep(0.2)
    note = [e for e in got if e["hook_event_name"] == "CloveNotification"]
    check("messages and calls go to the notch", len(note) == 3, got)
    check("on the app's own pill", [e["clove_agent"] for e in note] == ["app-whatsapp", "app-phone", "app-x"], note)
    check("with who and what", note[0]["sender"] == "Sam" and note[0]["text"] == "are you free tonight?" and note[1]["kind"] == "ringing")
    server.close()



asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

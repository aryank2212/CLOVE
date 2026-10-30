"""Replying to messages for him: only when it's on, only WhatsApp, never groups, never twice, never the wrong chat,
and he is told what was sent. Nothing real is sent: the model and Chrome are stand-ins."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import autoreply as AR  # noqa: E402
import browser_bridge  # noqa: E402
import notifications as N  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


def note(sender, body, platform="WhatsApp"):
    return N.Note(app="Google Chrome", title=sender, body=body, platform=platform)


calls, told = [], []
opened = {"name": None}


async def fake_bridge(act, timeout=25, **kw):
    calls.append((act, kw))
    if act == "wa_chat":
        name = opened["name"] or kw["name"]
        return f'opened WhatsApp chat "{name}"'
    if act == "wa_send":
        return f'sent: "{kw["text"]}"'
    return "ok"


browser_bridge.bridge.call = fake_bridge


async def main():
    prefs = {"announce": True, "forward": True, "autoreply": True}

    async def notify(text):
        told.append(text)
    a = SimpleNamespace(
        loop=asyncio.get_running_loop(), client=object(), dashboard=SimpleNamespace(prefs=prefs),
        dictation=SimpleNamespace(on=False), focus=SimpleNamespace(active=False),
        calls=SimpleNamespace(audible=lambda: False), wake=SimpleNamespace(wake=lambda why: None), notify=notify)
    ar = AR.AutoReply(a)
    a.autoreply = ar
    drafts = {"text": "Hi, this is CLOVE, Sam's assistant. He'll get back to you soon."}

    async def draft(n):
        return drafts["text"]
    ar.draft = draft
    w = N.Notifications(a)
    N.BATCH_S = 0.05

    # ---- what gets an automatic reply ---------------------------------------------------------------
    check("a WhatsApp message from a person does", ar.wanted(note("Priya", "are you free tonight?")))
    check("not Instagram (he decides there)", not ar.wanted(note("alex", "hey", "Instagram")))
    check("not a group (\"Sender: message\")", not ar.wanted(note("College gang", "Rohan: who's coming?")))
    prefs["autoreply"] = False
    check("nothing while the setting is off", not ar.wanted(note("Priya", "are you free tonight?")))
    prefs["autoreply"] = True

    # ---- a reply is sent once, to the right chat, and he is told ------------------------------------
    w.seen_note(note("Priya", "are you free tonight?"))
    await asyncio.sleep(0.3)
    sends = [c for c in calls if c[0] == "wa_send"]
    check("the reply goes to WhatsApp", len(sends) == 1 and "CLOVE" in sends[0][1]["text"])
    check("after opening the sender's own chat", calls[0] == ("wa_chat", {"name": "Priya"}))
    check("he is told who wrote and what was answered", told and "Priya" in told[-1] and "You replied" in told[-1])
    check("and not asked whether to reply", "Don't ask whether to reply" in told[-1])

    w.seen_note(note("Priya", "ok and tomorrow?"))
    await asyncio.sleep(0.3)
    check("the same person again soon: no second automatic reply", len([c for c in calls if c[0] == "wa_send"]) == 1)
    check("he is asked about that one instead", "ok and tomorrow?" in told[-1] and "like you to reply" in told[-1])

    # ---- skipped and failed replies fall back to asking him -----------------------------------------
    drafts["text"] = None                                   # the model said SKIP (a code, money, a company...)
    w.seen_note(note("HDFC Bank", "Your OTP is 482913"))
    await asyncio.sleep(0.3)
    check("a skipped message is not answered", len([c for c in calls if c[0] == "wa_send"]) == 1)
    check("he is asked about it as usual", "482913" in told[-1] and "like you to reply" in told[-1])

    drafts["text"] = "Hi, this is CLOVE."
    opened["name"] = "Mum (2)"                              # WhatsApp opened a different chat
    w.seen_note(note("Mum", "call me"))
    await asyncio.sleep(0.3)
    check("never sent when another chat opened", len([c for c in calls if c[0] == "wa_send"]) == 1)
    opened["name"] = None

    # ---- the hourly cap -----------------------------------------------------------------------------
    ar.sent.extend([AR.time.monotonic()] * AR.MAX_PER_HOUR)
    check("no more than MAX_PER_HOUR in an hour", not ar.wanted(note("Dev", "yo")))

    # ---- the model's answer is cleaned and checked --------------------------------------------------
    ar2 = AR.AutoReply(a)
    import llm

    async def fake_hedged(client, models, contents, cfg, **kw):
        fake_hedged.contents = contents
        return "m", fake_hedged.answer
    llm.hedged = fake_hedged
    fake_hedged.answer = "SKIP"
    check("SKIP means no reply", await ar2.draft(note("Bank", "pay now")) is None)
    fake_hedged.answer = '"Hi, this is CLOVE, Sam\'s assistant."'
    check("quotes around the reply are removed", await ar2.draft(note("Ann", "hi")) == "Hi, this is CLOVE, Sam's assistant.")
    check("the message reaches the model between markers", "<<<\nhi\n>>>" in fake_hedged.contents)
    fake_hedged.answer = "x" * 500
    check("an overlong answer is not sent", await ar2.draft(note("Ann", "hi")) is None)


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

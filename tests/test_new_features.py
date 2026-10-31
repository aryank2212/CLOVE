"""Wake word, earcons, learned commands, tool picking, dictation, focus mode, the control socket, Clove's MCP
server and machine names: the parts that need no microphone, model or network."""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    fails += not ok


def fake_assistant():
    a = SimpleNamespace(awaiting=False, busy=0, speaker=None, client=None, brain=None, active="hybrid")
    a.speaking = lambda: False
    a.calls = SimpleNamespace(audible=lambda: False)
    a.tools = SimpleNamespace(plan=None)
    a.ui = SimpleNamespace(send=lambda **k: None)
    a.stop_speaking = lambda: None
    return a


# ---- wake word ------------------------------------------------------------------------------------
import wake  # noqa: E402

p = wake.wake_pattern(["clove", "rose"])
for text, want in [("Clove, open YouTube.", True), ("Hey Rose, what time is it?", True), ("thanks clove", True),
                   ("Glove, play music", True), ("close the tab", False), ("sort the rows", False),
                   ("I bought cloves today and", False), ("open youtube", False)]:
    check(f"wake word {text!r} -> {want}", bool(p.search(text)) == want)

config.WAKE_WORD = True
a = fake_assistant()
g = wake.WakeGate(a)
g.recogniser = SimpleNamespace(model=None)
g._check = lambda pcm: (g._woken(pcm, "test"), setattr(g, "busy", False))    # pretend the name was heard
a.loop = SimpleNamespace(call_soon_threadsafe=lambda f, *x: None)
now = time.monotonic()
voice, quiet = b"\x10" * 1024, b"\x00" * 1024
out = [g.filter([voice], True, now + i * 0.03) for i in range(20)]
check("asleep: speech is held back", all(o is None for o in out))
g.filter([quiet], False, now + 0.6 + 0.5)                       # end of utterance -> checked -> woken
frames = g.take_replay()
check("woken: the utterance is replayed", len(frames) >= 15)
check("awake: audio passes", g.filter([voice], True, time.monotonic()) == [voice])
g.sleep()
check("sleep(): asleep again", g.filter([voice], True, time.monotonic()) is None)

# ---- earcons --------------------------------------------------------------------------------------
import sounds  # noqa: E402

pcm = sounds.pcm("wake")
check("earcon is short 24 kHz audio", 0.1 < len(pcm) / 2 / 24000 < 0.5)

# ---- learned commands -----------------------------------------------------------------------------
import learned  # noqa: E402

learned.PATH = Path(tempfile.mkdtemp()) / "learned.json"
L = learned.Learned()
for q in ["lofi beats", "daft punk", "arijit singh"]:
    L.observe(f"Clove, play {q} on youtube please", "play_youtube", {"query": q}, True)
check("learned after 3 varied examples", L.match("hey clove play coldplay yellow on youtube") ==
      ("play_youtube", {"query": "coldplay yellow"}))
L2 = learned.Learned()
for q in ["x", "y"]:
    L2.observe(f"play {q}{q}{q} on spotify", "play_spotify", {"query": q * 3}, True)
check("not learned after only 2 examples", L2.match("play abc on spotify") is None)
for n in (30, 50, 70):
    L.observe(f"set the volume to {n}", "volume", {"action": "set", "percent": n}, True)
check("numeric slot keeps its type", L.match("set the volume to 45") == ("volume", {"action": "set", "percent": 45}))
check("enum args are not slots", L.match("lower the volume to 20") is None)
for _ in range(5):
    L.observe("delete my downloads", "run_command", {"command": "rm -r ~/Downloads/*"}, True)
check("unsafe tools are never learned", L.match("delete my downloads") is None)
check("persisted to disk", learned.PATH.exists() and "play {query} on youtube" in learned.PATH.read_text())
check("forget_last removes one", "Forgotten" in L.forget_last())

# ---- tool picking ---------------------------------------------------------------------------------
from toolpick import CORE, Picker  # noqa: E402
from tools import DECLARATIONS  # noqa: E402

pk = Picker(DECLARATIONS)
names = {d.name for d in DECLARATIONS}
check("every CORE tool exists", CORE <= names, str(CORE - names))
for text, must in [("how is anton doing", "machine_overview"), ("restart jellyfin on the server", "service"),
                   ("play arijit singh on youtube", "play_youtube"), ("start dictation", "dictate"),
                   ("show me how to export in gimp", "guide"), ("fix the bug in my project", "delegate_to_agent")]:
    got = pk.names_for(text)
    check(f"tools for {text!r} include {must}", must in got and len(got) <= 40, f"{len(got)} tools")
check("picked tools are text-API safe (no behavior)", all(d.behavior is None for d in pk.pick("research x")))
pk.used({"service"})
check("recently used tools stay offered", "service" in pk.names_for("and now the other one"))

# ---- dictation ------------------------------------------------------------------------------------
import dictate  # noqa: E402

check("'stop dictation' ends it", bool(dictate.STOP.match("Stop dictation.")))
check("ordinary words don't end it", not dictate.STOP.match("we should stop the dictation app from crashing"))
t = "Dear Sam new line thanks for the notes new paragraph Aryan"
for rx, rep in dictate.SPOKEN:
    t = rx.sub(rep, t)
check("'new line' / 'new paragraph' become breaks", t == "Dear Sam\nthanks for the notes\n\nAryan", repr(t))

check("'Clove, ...' is for CLOVE", dictate.addressed("Clove, what time is it?") and dictate.addressed("hey klove open it"))
check("the word clove inside a sentence is still typed", not dictate.addressed("add a clove of garlic"))


class _Loop:
    def call_soon_threadsafe(self, fn, *a):
        fn(*a)


_calls = []
_fake = SimpleNamespace(loop=_Loop(), ui=SimpleNamespace(send=lambda **k: None), stop_speaking=lambda: None,
                        brain=SimpleNamespace(stt=SimpleNamespace(transcribe=lambda pcm: "Clove, what time is it?")),
                        on_ui=lambda m: _calls.append(m))
d = dictate.Dictation(_fake)
dictate.type_text = lambda text: _calls.append(("typed", text)) or "typed"
import sounds  # noqa: E402
sounds.play = lambda *a, **k: None
d.start(); d.stt = _fake.brain.stt
d._write(b"\0" * 32000)
check("saying CLOVE's name ends dictation and CLOVE answers it",
      not d.on and _calls == [{"type": "text", "text": "Clove, what time is it?"}], _calls)
d.start()
d.on_audio(b"\0" * 320, False, 1000.0)
d.on_audio(b"\0" * 320, False, 1000.0 + dictate.IDLE_STOP_S - 1)
check("dictation stays on through a pause", d.on)
d.on_audio(b"\0" * 320, False, 1000.0 + dictate.IDLE_STOP_S + 1)
check("two minutes without speech end it", not d.on)

# ---- focus mode -----------------------------------------------------------------------------------
import focus  # noqa: E402


async def focus_test():
    fa = fake_assistant()
    fa.wake = SimpleNamespace(wake=lambda why: None)
    f = focus.Focus(fa)
    f.start(25)
    held = f.hold(SimpleNamespace(status="done"))
    passed = not f.hold(SimpleNamespace(status="failed"))
    delivered = []

    async def deliver(job):
        delivered.append(job)
    fa.deliver_job = deliver
    msg = f.stop()
    await asyncio.sleep(0)
    return held, passed, msg, delivered

held, passed, msg, delivered = asyncio.run(focus_test())
check("focus holds finished jobs", held)
check("focus lets failures through", passed)
check("focus end delivers what was held", len(delivered) == 1 and "1 things finished" in msg, msg)

# ---- control socket: an agent's question and his answer --------------------------------------------
import ctl  # noqa: E402


async def ask_test():
    fa = fake_assistant()
    fa.wake = SimpleNamespace(wake=lambda why: None)
    notes = []

    async def notify(n):
        notes.append(n)
    fa.notify = notify
    task = asyncio.create_task(ctl.agent_ask(fa, "Postgres or SQLite?", timeout=5))
    await asyncio.sleep(0.05)
    r = ctl.answer("SQLite, keep it simple")
    return await task, r, notes

got, r, notes = asyncio.run(ask_test())
check("agent question reaches the brain", notes and "Postgres or SQLite?" in notes[0])
check("his answer goes back to the agent", got == "The user answered: SQLite, keep it simple" and "Passed" in r, got)
check("no question -> nothing to answer", "No agent" in ctl.answer("hello"))

# ---- Clove's MCP server ---------------------------------------------------------------------------
req = "\n".join(json.dumps(x) for x in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
out = subprocess.run([sys.executable, str(ROOT / "clove_mcp.py")], input=req, capture_output=True, text=True,
                     timeout=20).stdout.strip().splitlines()
replies = [json.loads(x) for x in out]
check("MCP: initialize + tools/list answered", len(replies) == 2 and replies[0]["id"] == 1)
check("MCP: offers ask_user/tell_user/user_context",
      {t["name"] for t in replies[1]["result"]["tools"]} == {"ask_user", "tell_user", "user_context"})

# ---- machines -------------------------------------------------------------------------------------
import machines  # noqa: E402

check("machine names include local and anton", machines.names()[:1] == ["local"] and "anton" in machines.names())
check("'this pc' means local", machines.resolve("this") == "local")
check("unknown machine is refused", machines.run("nowhere", "true").startswith("error"))
check("catastrophic commands are refused", machines.run("local", "rm -rf /").startswith("refused"))
check("local commands run", machines.run("local", "echo hi", stdin="").endswith("hi"))

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

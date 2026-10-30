"""The command-centre backend: real telemetry, workspace info, service-check states, the window feed and its replay
order, settings validation, and the safety rules the window surfaces (deletions need approval, no passwords in
commands). No network needed except a localhost SSH-free path."""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

config.STATE_DIR = Path(tempfile.mkdtemp())
import dashboard  # noqa: E402

dashboard.PREFS = config.STATE_DIR / "ui.json"
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    fails += not ok


# ---- telemetry is measured ------------------------------------------------------------------------
t = dashboard.Telemetry()
first = t.sample()
time.sleep(0.6)
s = t.sample()
check("first sample has no CPU % yet (needs two readings)", "cpu" not in first)
check("CPU % in range", 0 <= s["cpu"] <= 100, s.get("cpu"))
check("memory used <= total", 0 < s["mem_used"] <= s["mem_total"])
check("disks are real and deduplicated", s["disks"] and len({(d["total"], d["used"] // 2**30) for d in s["disks"]}) == len(s["disks"]))
check("history only holds measured values", all(isinstance(v, float) for v in s["hist"]["cpu"]))
check("GPU is either measured or explicitly None", s["gpu"] is None or 0 <= s["gpu"]["util"] <= 100)

# ---- workspace --------------------------------------------------------------------------------
w = dashboard.workspace(str(ROOT))
check("this repo is a git workspace", w["ok"] and w["git"] and w["branch"] and w["name"])
plain = tempfile.mkdtemp()
check("a plain folder is not called a repository", dashboard.workspace(plain) == {"ok": True, "path": plain,
                                                                               "name": Path(plain).name, "git": False})
check("a missing folder is unavailable", dashboard.workspace("/no/such/dir") == {"ok": False})

# ---- service checks report honest states --------------------------------------------------------
def bad_client(msg):
    def get(model):
        raise RuntimeError(msg)
    return SimpleNamespace(models=SimpleNamespace(get=get))


config.MACHINES = {}
fake = SimpleNamespace(client=bad_client("401 API key not valid"), brains={}, active="hybrid", connected=True)
old_key, config.GEMINI_API_KEY = config.GEMINI_API_KEY, "x"
items = {i["key"]: i for i in dashboard.check_services(fake, slow=False)}
check("rejected key -> warn, says authentication", items["gemini"]["state"] == "warn" and "authentication" in items["gemini"]["detail"])
fake.client = bad_client("Connection refused")
items = {i["key"]: i for i in dashboard.check_services(fake, slow=False)}
check("unreachable API -> down", items["gemini"]["state"] == "down")
config.GEMINI_API_KEY = ""
items = {i["key"]: i for i in dashboard.check_services(fake, slow=False)}
check("no key -> off, not an error", items["gemini"]["state"] == "off")
config.GEMINI_API_KEY = old_key
check("every check is timestamped", all(i["checked"] > 0 for i in items.values()))
check("agent probe can be deferred", items["agents"].get("pending") is True)
check("states are only ok/warn/down/off", {i["state"] for i in items.values()} <= {"ok", "warn", "down", "off"})

# ---- the window feed: order, continuation, in-place updates, replay -------------------------------
import ui as ui_mod  # noqa: E402

u = ui_mod.UI(lambda m: None)
u.send(type="caption", who="you", text="how is ", new=True)
u.send(type="caption", who="you", text="anton?", new=False)
u.send(type="activity", id="a1", kind="self", label="Machine check", state="running")
u.send(type="caption", who="clove", text="Anton is fine.", new=True)
u.send(type="activity", id="a1", kind="self", label="Machine check", state="ok", detail="")
u.send(type="notice", text="Warming up…")
u.send(type="notice", text="")
kinds = [m["type"] for m in u.feed]
check("feed keeps the order things happened", kinds == ["caption", "activity", "caption"], kinds)
check("continued caption joins the same message", u.feed[0]["text"] == "how is anton?")
check("activity updates in place, keeps its start time", u.feed[1]["state"] == "ok" and u.feed[1]["ts"] <= u.feed[1]["updated"])
check("the cleared notice is what a reconnecting window sees last", json.loads(u.latest["notice"])["text"] == "")
check("notification history keeps the non-empty notice", any("Warming up" in e for e in u.events))

# ---- compact window commands: Lua dispatchers (Hyprland 0.56+), classic words otherwise ---------------
sent_h = []
real_hypr = dashboard._hypr
dashboard._hypr = lambda *a: (sent_h.append(a), "ok")[1]
dashboard._dispatch("address:0x1", {"float": ["enable"], "pin": ["enable"], "size": (380, 560), "at": (1138, 286)})
check("Lua: float, size, place, pin", [x[1] for x in sent_h] == [
    'hl.dsp.window.float({ window = "address:0x1", action = "enable" })',
    'hl.dsp.window.resize({ window = "address:0x1", x = 380, y = 560 })',
    'hl.dsp.window.move({ window = "address:0x1", x = 1138, y = 286 })',
    'hl.dsp.window.pin({ window = "address:0x1", action = "enable" })'], sent_h)
sent_h.clear()
dashboard._hypr = lambda *a: (sent_h.append(a), "error: unknown dispatcher" if a[0] == "dispatch" else "ok")[1]
dashboard._dispatch("address:0x1", {"float": ["disable"], "pin": ["disable"], "size": None, "at": None})
check("older Hyprland: the classic batch", sent_h[-1] == ("--batch", "dispatch settiled address:0x1 ; dispatch pin address:0x1"), sent_h)
dashboard._hypr = real_hypr

# ---- where the window opens -----------------------------------------------------------------------
launched = []
real_which, real_popen = ui_mod.shutil.which, ui_mod.subprocess.Popen
ui_mod.subprocess.Popen = lambda argv, **k: launched.append(argv)
ui_mod.shutil.which = lambda name: {"clove-notch": "/x/clove-notch", "google-chrome": "/x/chrome"}.get(name)
ui_mod.open_window("http://127.0.0.1:1/?t=abcdefghij")
check("with Clove Notch installed, the window is its Assistant page", launched[-1] == ["/x/clove-notch", "--page", "assistant"])
ui_mod.open_window("http://127.0.0.1:1/?t=abcdefghij", compact=True)
check("the compact companion stays a Chrome window", launched[-1][0] == "/x/chrome" and "--window-size=380,560" in launched[-1])
ui_mod.shutil.which = lambda name: {"google-chrome": "/x/chrome"}.get(name)
ui_mod.open_window("http://127.0.0.1:1/?t=abcdefghij")
check("without Clove Notch: a Chrome app window", launched[-1][0] == "/x/chrome" and launched[-1][1].startswith("--app="))
ui_mod.shutil.which, ui_mod.subprocess.Popen = real_which, real_popen
check("reduce motion is a saved setting", "reduce" in dashboard.DEFAULT_PREFS)

# ---- each response has one content type (WebKit, in Clove Notch's window, reads the first) ------------
async def served():
    srv = ui_mod.UI(lambda m: None)
    await srv.start()
    out = {}
    for path in ("/clove.css", "/clove.js", f"/?t={srv.token}"):
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        head = (await r.read()).split(b"\r\n\r\n")[0].decode().lower().splitlines()
        out[path.split("?")[0]] = [l.split(":", 1)[1].strip() for l in head if l.startswith("content-type:")]
        w.close()
    srv.server.close()
    return out


types = asyncio.run(served())
check("one Content-Type per response, the right one", types == {"/clove.css": ["text/css; charset=utf-8"],
      "/clove.js": ["text/javascript; charset=utf-8"], "/": ["text/html; charset=utf-8"]}, types)

# ---- settings from the window are validated -------------------------------------------------------
sent = []
a = SimpleNamespace(wake=SimpleNamespace(enabled=True, awake_until=0), ui=SimpleNamespace(send=lambda **k: sent.append(k)))
d = dashboard.Dashboard.__new__(dashboard.Dashboard)
d.a, d.prefs, d._ws_sent = a, dict(dashboard.DEFAULT_PREFS), None
d.on_ui({"type": "setting", "key": "wake", "value": False})
check("wake word can be switched off", a.wake.enabled is False and d.prefs["wake"] is False)
check("settings are saved", json.loads(dashboard.PREFS.read_text())["wake"] is False)
d.on_ui({"type": "setting", "key": "sudo_password", "value": "x"})
check("unknown settings are ignored", "sudo_password" not in d.prefs)
d.on_ui({"type": "setting", "key": "wake", "value": "yes"})
check("wrong value types are ignored", d.prefs["wake"] is False)
d.on_ui({"type": "setting", "key": "workspace", "value": "/no/such/folder"})
check("a missing workspace folder is refused", d.prefs["workspace"] == "" and any(m.get("type") == "toast" for m in sent))

# ---- safety rules the window relies on ----------------------------------------------------------
import deletion_guard  # noqa: E402
import machines  # noqa: E402

for cmd, want in [('docker ps --format "table {{.Names}}"', False), ("docker rm -f old", True), ("docker compose down", True),
                  ("docker restart jellyfin", False), ("rm -rf build", True), ("ls; rm x", True), ("cat format.txt", False),
                  ("git reset --hard HEAD~1", True), ("git status", False), ("sudo apt purge foo", True), ("grep -r alarm .", False)]:
    check(f"deletion? {cmd!r} -> {want}", deletion_guard.is_deletion("run_command", {"command": cmd}) == want)
for cmd in ["echo 'pw' | sudo -S docker ps", "printf pw | sudo -S ls", "sudo -S whoami <<< pw"]:
    check(f"password in command refused: {cmd!r}", machines.run("local", cmd, stdin="").startswith("refused"))
check("plain sudo commands are not refused by that rule", not machines.PASSWORD_PIPE.search("sudo docker ps"))

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

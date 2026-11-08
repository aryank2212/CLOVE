"""Live data for the command-centre window: this PC's telemetry, the health of every service Clove uses, the current
workspace, saved interface settings, and window control (compact companion / command centre).

Everything here is measured, not assumed: telemetry comes from /proc and nvidia-smi, each service has a real check
with a timestamp, and anything that can't be measured is reported as unavailable rather than guessed."""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from collections import deque
from pathlib import Path

import config

log = logging.getLogger("clove.dashboard")
PREFS = config.STATE_DIR / "ui.json"
DEFAULT_PREFS = {"wake": config.WAKE_WORD, "earcons": config.EARCONS, "compact": False, "pin": True, "reduce": False, "announce": True, "forward": True, "autoreply": False, "answercalls": False, "callhindi": False, "musicaware": True,
                 "workspace": ""}
HISTORY = 60                                       # samples kept per metric (2 minutes at 2 s)
SERVICE_EVERY_S = 45


def load_prefs() -> dict:
    try:
        return {**DEFAULT_PREFS, **json.loads(PREFS.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT_PREFS)


def _run(argv: list[str], timeout: float = 5) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


# ---- telemetry --------------------------------------------------------------------------------
class Telemetry:
    def __init__(self):
        self.prev_cpu = None
        self.prev_net = None
        self.hist = {k: deque(maxlen=HISTORY) for k in ("cpu", "mem", "gpu", "net")}
        self.gpu_ok = bool(shutil.which("nvidia-smi"))

    @staticmethod
    def _cpu_times():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        return sum(v), idle

    @staticmethod
    def _net_bytes():
        rx = tx = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, data = line.split(":", 1)
                if name.strip() in ("lo",) or name.strip().startswith(("docker", "veth", "br-")):
                    continue
                d = data.split()
                rx, tx = rx + int(d[0]), tx + int(d[8])
        return rx, tx, time.monotonic()

    def _gpu(self) -> dict | None:
        if not self.gpu_ok:
            return None
        p = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                  "--format=csv,noheader,nounits"], 4)
        if not p or p.returncode != 0 or not p.stdout.strip():
            return None
        u, used, total, temp, name = [x.strip() for x in p.stdout.strip().splitlines()[0].split(",")]
        return {"util": float(u), "mem_used": float(used), "mem_total": float(total), "temp": float(temp), "name": name}

    def sample(self) -> dict:
        now = time.time()
        out = {"ts": now}
        total, idle = self._cpu_times()
        if self.prev_cpu:
            dt, di = total - self.prev_cpu[0], idle - self.prev_cpu[1]
            out["cpu"] = round(100 * (1 - di / dt), 1) if dt > 0 else 0.0
        self.prev_cpu = (total, idle)
        out["cores"] = os.cpu_count()
        out["load"] = [round(x, 2) for x in os.getloadavg()]
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) * 1024
        out["mem_total"], out["mem_used"] = mem["MemTotal"], mem["MemTotal"] - mem["MemAvailable"]
        out["mem"] = round(100 * out["mem_used"] / out["mem_total"], 1)
        rx, tx, t = self._net_bytes()
        if self.prev_net:
            dt = t - self.prev_net[2]
            out["net_rx"], out["net_tx"] = max(0, (rx - self.prev_net[0]) / dt), max(0, (tx - self.prev_net[1]) / dt)
        self.prev_net = (rx, tx, t)
        out["gpu"] = self._gpu()
        disks, seen = [], set()
        for label, path in (("/", "/"), ("home", str(Path.home())), ("clove", str(config.ROOT))):
            try:
                u = shutil.disk_usage(path)
                if (u.total, u.used // 2**30) in seen:      # btrfs subvolumes: same disk, different st_dev
                    continue
                seen.add((u.total, u.used // 2**30))
                disks.append({"label": label, "path": path, "used": u.used, "total": u.total})
            except OSError:
                pass
        out["disks"] = disks
        with open("/proc/uptime") as f:
            out["uptime"] = float(f.read().split()[0])
        for k, v in (("cpu", out.get("cpu")), ("mem", out["mem"]),
                     ("gpu", out["gpu"]["util"] if out["gpu"] else None),
                     ("net", (out.get("net_rx", 0) + out.get("net_tx", 0)) if "net_rx" in out else None)):
            if v is not None:
                self.hist[k].append(round(v, 1))
        out["hist"] = {k: list(v) for k, v in self.hist.items()}
        return out


# ---- service health ---------------------------------------------------------------------------
def _svc(key, name, state, detail, **extra) -> dict:
    """state: ok (reachable and working) | warn (configured, needs attention) | down (configured, unreachable) |
    off (not configured or not in use)."""
    return {"key": key, "name": name, "state": state, "detail": detail, "checked": time.time(), **extra}


def check_services(a, slow: bool = True) -> list[dict]:
    """slow=False skips the coding-agent probe (its first run can take ~20 s while CLIs are asked)."""
    out = []
    # Gemini API: a free metadata call proves the key works and the API is reachable
    if not config.GEMINI_API_KEY:
        out.append(_svc("gemini", "Gemini API", "off", "No GEMINI_API_KEY in .env: Gemini, Hybrid, vision are off"))
    elif a.client:
        model = config.HYBRID_MODELS[0] if config.HYBRID_MODELS else config.BRAIN_MODELS[0]
        try:
            a.client.models.get(model=model)
            out.append(_svc("gemini", "Gemini API", "ok", f"key accepted · {model} reachable"))
        except Exception as e:
            msg = str(e)
            auth = any(x in msg for x in ("401", "403", "API key", "PERMISSION_DENIED", "UNAUTHENTICATED"))
            out.append(_svc("gemini", "Gemini API", "warn" if auth else "down",
                            "authentication failed: check GEMINI_API_KEY" if auth else f"unreachable ({msg[:80]})"))
    live = a.brains.get("gemini")
    if a.active == "gemini":
        out.append(_svc("live", "Gemini Live session", "ok" if a.connected else "warn",
                        f"{config.LIVE_MODEL} · session open" if a.connected else "reconnecting"))
    elif live:
        out.append(_svc("live", "Gemini Live session", "off", "not in use (another brain is active)"))
    # Ollama (Qwen): stopped when idle on purpose, so "stopped" is not an error
    try:
        v = json.load(urllib.request.urlopen(config.OLLAMA_HOST + "/api/version", timeout=1.5)).get("version", "")
        out.append(_svc("ollama", "Ollama (Qwen)", "ok", f"running {v} · {config.LOCAL_MODEL}"))
    except (OSError, ValueError):
        installed = shutil.which("ollama") or (Path.home() / ".local/bin/ollama").exists()
        out.append(_svc("ollama", "Ollama (Qwen)", "off",
                        "stopped · starts when Qwen or Kilo is used" if installed else "not installed"))
    # Chrome extension
    from browser_bridge import SEEN, bridge, wanted_version
    if bridge.connected:
        st = "warn" if bridge.stale else "ok"
        out.append(_svc("chrome", "Chrome extension", st, f"v{bridge.ext_version} connected"
                        + (f" · v{wanted_version()} on disk, reloading" if bridge.stale else "")))
    else:
        out.append(_svc("chrome", "Chrome extension", "warn" if SEEN.exists() else "off",
                        "installed, not connected (Chrome closed?)" if SEEN.exists() else "not installed (./install_extension.sh)"))
    # Machines over SSH
    for name, target in config.MACHINES.items():
        t0 = time.monotonic()
        p = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", target, "true"], 8)
        ms = int((time.monotonic() - t0) * 1000)
        if p and p.returncode == 0:
            sudo = "sudo configured" if config.MACHINE_SUDO.get(name) else "no sudo password"
            out.append(_svc(f"ssh-{name}", f"{name.title()} (SSH)", "ok", f"{target} · {ms} ms · {sudo}"))
        else:
            err = (p.stderr.strip().splitlines() or ["timed out"])[-1][:90] if p else "ssh missing"
            out.append(_svc(f"ssh-{name}", f"{name.title()} (SSH)", "down", f"{target} · {err}"))
    # Anton's Forge
    if config.MACHINES.get("anton"):
        if not config.ANTON_FORGE_TOKEN:
            out.append(_svc("forge", "Anton Forge", "warn", "no ANTON_FORGE_TOKEN in .env"))
        else:
            try:
                url = f"http://{config.ANTON_HOST}:{config.ANTON_FORGE_PORT}/health"
                d = json.load(urllib.request.urlopen(url, timeout=3))
                out.append(_svc("forge", "Anton Forge", "ok", f"autonomy level {d.get('autonomy_level')} · {d.get('tools')} tools"))
            except (OSError, ValueError) as e:
                out.append(_svc("forge", "Anton Forge", "down", f"unreachable ({str(e)[:60]})"))
    # Coding agents
    out.append(_agents_svc() if slow else _svc("agents", "Coding agents", "off", "checking…", pending=True))
    # Phone inbox
    if config.PHONE_INBOX:
        ok = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
        out.append(_svc("phone", "Telegram inbox", "ok" if ok else "warn", "polling" if ok else "missing bot token / chat id"))
    else:
        out.append(_svc("phone", "Telegram inbox", "off", "off (PHONE_INBOX=on in .env)"))
    return out


def _agents_svc() -> dict:
    try:
        import cli_adapter
        chain = cli_adapter.chain()
        cli_adapter.claude_ready()
        detail = ", ".join(chain[:5]) or "none installed"
        detail += {"no": " · Claude Code not logged in", "unknown": " · Claude Code login unknown (check timed out)"}.get(
            cli_adapter.claude_auth_state, "")
        return _svc("agents", "Coding agents", "ok" if chain else "off", detail, items=chain)
    except Exception as e:
        return _svc("agents", "Coding agents", "down", str(e)[:80])


# ---- workspace --------------------------------------------------------------------------------
def workspace(folder: str) -> dict:
    if not folder or not Path(folder).is_dir():
        return {"ok": False}
    git = lambda *x: _run(["git", "-C", folder, *x], 4)                      # noqa: E731
    top = git("rev-parse", "--show-toplevel")
    if not top or top.returncode != 0:
        return {"ok": True, "path": folder, "name": Path(folder).name, "git": False}
    root = top.stdout.strip()
    branch = (git("rev-parse", "--abbrev-ref", "HEAD").stdout or "").strip()
    status = [l for l in (git("status", "--porcelain").stdout or "").splitlines() if l.strip()]
    last = (git("log", "-1", "--format=%h\t%s\t%cr").stdout or "").strip().split("\t")
    return {"ok": True, "git": True, "path": root, "name": Path(root).name, "branch": branch,
            "changed": len(status), "files": [l[3:] for l in status[:8]],
            "commit": {"hash": last[0], "subject": last[1], "when": last[2]} if len(last) == 3 else None,
            "checked": time.time()}


# ---- the window (Hyprland) ------------------------------------------------------------------------
def _hypr(*args: str) -> str:
    if not shutil.which("hyprctl") or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ""
    p = _run(["hyprctl", *args], 3)
    return p.stdout if p else ""


def _clove_window() -> dict | None:
    try:
        return next((c for c in json.loads(_hypr("clients", "-j") or "[]") if c.get("title") == "CLOVE"
                     and "notch" not in (c.get("class", "") + c.get("initialClass", "")).lower()), None)
    except ValueError:
        return None


def set_window(mode: str, pin: bool) -> bool:
    """compact: a small floating window in the bottom-right corner (pinned to every workspace if `pin`); expanded:
    back into the tiling layout. Returns False when there is no window manager to ask (the page resizes itself)."""
    w = _clove_window()
    if not w:
        return False
    addr = f"address:{w['address']}"
    try:
        mon = next(m for m in json.loads(_hypr("monitors", "-j")) if m["id"] == w["monitor"])
    except (ValueError, StopIteration):
        return False
    W, H = int(mon["width"] / mon["scale"]), int(mon["height"] / mon["scale"])
    lua = {"float": [], "pin": [], "size": None, "at": None}
    if mode == "compact":
        cw, ch = 380, min(560, H - 80)
        lua.update(float=["enable"], size=(cw, ch), at=(mon["x"] + W - cw - 18, mon["y"] + H - ch - 18))
        if pin != bool(w.get("pinned")):
            lua["pin"] = ["enable" if pin else "disable"]
    else:
        if w.get("pinned"):
            lua["pin"] = ["disable"]
        if w["floating"]:
            lua["float"] = ["disable"]
    _dispatch(addr, lua)
    return True


def _dispatch(addr: str, do: dict):
    """Hyprland 0.56+ with a Lua config takes dispatchers as Lua (hl.dsp.window.*); older ones the classic words.
    Lua first; if Hyprland doesn't take it, the classic batch."""
    win = f'window = "{addr}"'
    lua = [f'hl.dsp.window.float({{ {win}, action = "{a}" }})' for a in do["float"]]
    if do["size"]:
        lua.append(f"hl.dsp.window.resize({{ {win}, x = {do['size'][0]}, y = {do['size'][1]} }})")
    if do["at"]:
        lua.append(f"hl.dsp.window.move({{ {win}, x = {do['at'][0]}, y = {do['at'][1]} }})")
    lua += [f'hl.dsp.window.pin({{ {win}, action = "{a}" }})' for a in do["pin"]]
    if not lua:
        return
    if all(_hypr("dispatch", cmd).strip() == "ok" for cmd in lua):
        return
    classic = [f"dispatch {'setfloating' if a == 'enable' else 'settiled'} {addr}" for a in do["float"]]
    if do["size"]:
        classic.append(f"dispatch resizewindowpixel exact {do['size'][0]} {do['size'][1]},{addr}")
    if do["at"]:
        classic.append(f"dispatch movewindowpixel exact {do['at'][0]} {do['at'][1]},{addr}")
    classic += [f"dispatch pin {addr}" for _ in do["pin"]]          # classic pin toggles; only sent when it differs
    _hypr("--batch", " ; ".join(classic))


# ---- the coordinator ----------------------------------------------------------------------------
class Dashboard:
    def __init__(self, a):
        self.a = a
        self.prefs = load_prefs()
        self.telemetry = Telemetry()
        self.last_ws = self.prefs.get("workspace", "")
        self._ws_sent = None
        self._refresh = asyncio.Event()
        self.apply_prefs()

    def apply_prefs(self):
        self.a.wake.enabled = bool(self.prefs["wake"])
        if not self.a.wake.enabled:
            self.a.wake.awake_until = 0
        config.EARCONS = bool(self.prefs["earcons"])

    def save(self):
        try:
            PREFS.parent.mkdir(parents=True, exist_ok=True)
            PREFS.write_text(json.dumps(self.prefs, indent=1))
        except OSError as e:
            log.warning("could not save interface settings: %s", e)

    def info(self) -> dict:
        return {"type": "info", "version": _version(), "user": config.USER_NAME, "live_model": config.LIVE_MODEL,
                "hybrid_models": config.HYBRID_MODELS, "local_model": config.LOCAL_MODEL, "ollama": config.OLLAMA_HOST,
                "machines": {k: v for k, v in config.MACHINES.items()},
                "sudo": {k: bool(v) for k, v in config.MACHINE_SUDO.items()} | {"local": bool(config.SUDO_PASSWORD)},
                "key": bool(config.GEMINI_API_KEY), "agents": config.AGENT_PRIORITY,
                "wake_names": config.WAKE_NAMES, "voice": config.VOICE, "prefs": self.prefs}

    async def run(self):
        ui = self.a.ui
        ui.send(**self.info())
        asyncio.create_task(self._services_loop())
        asyncio.create_task(self._apply_window_soon())
        n, seen = 0, None
        from browser_bridge import bridge
        while True:
            now = (bridge.connected, self.a.active, self.a.connected)
            if now != seen:                         # a connection changed: re-check services at once
                if seen is not None:
                    self._refresh.set()
                seen = now
            try:
                ui.send(type="telemetry", **await asyncio.to_thread(self.telemetry.sample))
                if n % 3 == 0:
                    await self._workspace()
            except Exception as e:
                log.debug("dashboard sample failed: %s", e)
            n += 1
            await asyncio.sleep(2)

    async def _services_loop(self):
        while True:
            try:
                items = await asyncio.to_thread(check_services, self.a, False)     # fast ones first
                self.a.ui.send(type="services", items=items, checked=time.time())
                items = await asyncio.to_thread(check_services, self.a, True)
                self.a.ui.send(type="services", items=items, checked=time.time())
            except Exception as e:
                log.warning("service checks failed: %s", e)
            self._refresh.clear()
            try:
                await asyncio.wait_for(self._refresh.wait(), SERVICE_EVERY_S)
            except asyncio.TimeoutError:
                pass

    async def _workspace(self):
        import deskctx
        folder = self.prefs.get("workspace") or ""
        pinned = bool(folder)
        if not pinned:
            f = (await asyncio.to_thread(deskctx.current)).get("folder", "")
            if f and f != str(Path.home()) and (await asyncio.to_thread(workspace, f)).get("git"):
                self.last_ws = f
            folder = self.last_ws
        w = await asyncio.to_thread(workspace, folder)
        w["pinned"], w["source"] = pinned, "chosen in settings" if pinned else "focused terminal"
        key = json.dumps({k: v for k, v in w.items() if k != "checked"}, sort_keys=True)
        if key != self._ws_sent:
            self._ws_sent = key
            self.a.ui.send(type="workspace", **w)

    async def _apply_window_soon(self):
        for _ in range(20):                         # the window appears a moment after start-up
            await asyncio.sleep(0.5)
            if await asyncio.to_thread(_clove_window):
                if self.prefs["compact"]:
                    await asyncio.to_thread(set_window, "compact", self.prefs["pin"])
                return

    # ---- messages from the window ------------------------------------------------------------
    def on_ui(self, m: dict) -> bool:
        t = m.get("type")
        if t == "setting":
            k, v = m.get("key"), m.get("value")
            if k in ("wake", "earcons", "pin", "reduce", "announce", "forward", "autoreply", "answercalls", "callhindi", "musicaware") and isinstance(v, bool):
                self.prefs[k] = v
            elif k == "workspace" and isinstance(v, str):
                v = os.path.expanduser(v.strip())
                if v and not Path(v).is_dir():
                    self.a.ui.send(type="toast", level="warn", text=f"Not a folder: {v}")
                    return True
                self.prefs[k] = v
                self._ws_sent = None
            else:
                return True
            self.apply_prefs()
            self.save()
            self.a.ui.send(**self.info())
            if k == "pin" and self.prefs["compact"]:
                asyncio.create_task(asyncio.to_thread(set_window, "compact", self.prefs["pin"]))
            return True
        if t == "window":
            mode = "compact" if m.get("mode") == "compact" else "expanded"
            self.prefs["compact"] = mode == "compact"
            self.save()

            async def go():
                ok = await asyncio.to_thread(set_window, mode, self.prefs["pin"])
                self.a.ui.send(type="window", mode=mode, managed=ok)
            asyncio.create_task(go())
            return True
        if t == "refresh":
            self._refresh.set()
            return True
        if t == "check" and m.get("what") == "machine_overview":
            machine = str(m.get("machine") or "local")

            async def check():
                import machines
                out = await asyncio.to_thread(machines.overview, machine)
                self.a.ui.send(type="overview", machine=machine, text=out, ts=time.time())
            asyncio.create_task(check())
            return True
        if t == "wake":
            self.a.wake.wake("window")
            import sounds
            sounds.play(self.a, "wake")
            return True
        if t == "ctl":
            import ctl

            async def run():
                out = await ctl.command(self.a, str(m.get("cmd", ""))[:200])
                self.a.ui.send(type="toast", level="info", text=out)
            asyncio.create_task(run())
            return True
        return False


def _version() -> str:
    p = _run(["git", "-C", str(config.ROOT), "describe", "--always", "--dirty"], 3)
    return p.stdout.strip() if p and p.returncode == 0 else ""

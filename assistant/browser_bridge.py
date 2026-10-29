"""Local websocket server the Clove Hands Chrome extension connects to. Only that extension's origin is accepted
(a web page can't open this socket). call() sends one command and waits for the extension's reply."""
import asyncio
import itertools
import json
import logging

import websockets
from websockets.asyncio.server import serve

import config

log = logging.getLogger("clove.bridge")
EXTENSION_ID = "acgjeghbhoabchdclfeckhokjjaikoaa"        # fixed by the "key" in chrome_extension/manifest.json
ORIGIN = f"chrome-extension://{EXTENSION_ID}"


def wanted_version() -> str:
    try:
        return json.loads((config.ROOT / "chrome_extension/manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return ""
ACTIONS = ("context", "tabs", "read", "text", "selected", "links", "find", "open", "new_window", "close", "switch", "navigate",
           "back", "forward", "reload", "pin", "unpin", "mute", "unmute", "duplicate", "reopen", "zoom", "group", "history",
           "bookmark", "click", "hover", "drag", "check", "type", "clear", "fill", "key", "scroll", "wait_for", "media", "batch",
           "wa_chat", "wa_send", "wa_join_call", "chat_links", "call_state", "call_isolate", "call_release", "wait")


class Bridge:
    def __init__(self):
        self.ws = None
        self.pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._server = None
        self.active: dict = {}          # the tab he is looking at: {id, title, url, app}, pushed by the extension
        self.loop = None
        self.ext_version = ""           # version the connected extension reports
        self.on_stale = None            # called when the connected extension is older than the one on disk
        self._tried_at = -1e9           # last time ensure_connected() waited for the extension in vain
        self.on_change = None           # called with the new screen note whenever what he looks at changes

    @property
    def stale(self) -> bool:
        """The extension loaded in Chrome is older than the files on disk (Chrome only picks up changes on 'Reload')."""
        want = wanted_version()
        return bool(self.ws and want and self.ext_version != want)

    @property
    def connected(self) -> bool:
        return self.ws is not None

    def screen_note(self) -> str:
        """One line for the models: what is on his screen right now (empty when Chrome isn't connected)."""
        a = self.active
        if not (self.ws and a):
            return ""
        note = f"{a.get('app') or a.get('url', '')[:50]} - {a.get('title', '')[:60]}".strip(" -")
        return note + (f" (chat with {a['chat']} is open)" if a.get("chat") else "")

    async def start(self):
        self.loop = asyncio.get_running_loop()
        try:
            self._server = await serve(self._handler, "127.0.0.1", config.BRIDGE_PORT, origins=[ORIGIN])
            log.info("browser bridge on 127.0.0.1:%s", config.BRIDGE_PORT)
        except OSError as e:
            log.error("browser bridge not started (%s)", e)

    async def _handler(self, ws):
        self.ws = ws
        log.info("Chrome extension connected")
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if "ping" in msg:
                    await ws.send('{"pong":1}')
                elif "hello" in msg:
                    self.ext_version = str(msg.get("version", ""))
                    try:
                        SEEN.parent.mkdir(parents=True, exist_ok=True)
                        SEEN.write_text(self.ext_version)          # installed once: never ask to install again
                    except OSError:
                        pass
                    if self.stale:
                        asyncio.create_task(self._update(ws))
                elif "state" in msg:
                    self.active = msg["state"]
                    if self.on_change:
                        try:
                            self.on_change(self.screen_note())
                        except Exception:
                            log.exception("screen change handler")
                    try:
                        import memory
                        if self.active.get("app"):
                            memory.set_focus("on screen", self.screen_note())
                    except Exception:
                        pass
                elif "id" in msg and (fut := self.pending.pop(msg["id"], None)) and not fut.done():
                    fut.set_result(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            if self.ws is ws:
                self.ws = None
                self.active = {}
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Chrome disconnected"))
            self.pending.clear()
            log.info("Chrome extension disconnected")

    async def _update(self, ws):
        """A newer extension is on disk: tell it to reload itself from the folder. Only if it can't (a version from
        before self-reload existed) is the user asked, once, to click reload."""
        have = self.ext_version
        log.info("Chrome extension v%s is older than v%s on disk; asking it to reload itself", have, wanted_version())
        try:
            await ws.send(json.dumps({"id": 0, "cmd": "self_reload"}))
        except Exception:
            pass
        await asyncio.sleep(SELF_RELOAD_WAIT_S)
        if self.stale and self.ext_version == have and self.on_stale:
            try:
                self.on_stale(have, wanted_version())
            except Exception:
                log.exception("stale handler")

    async def ensure_connected(self, wait: float = 15) -> bool:
        """Not connected: start Chrome if it isn't running, then give the extension a few seconds to connect (it
        retries every few seconds, and Chrome wakes it at start-up)."""
        if self.ws:
            return True
        import time
        if time.monotonic() - self._tried_at < RETRY_AFTER_S:      # just tried and failed: don't make him wait again
            return False
        self._tried_at = time.monotonic()
        import shutil
        import subprocess
        running = subprocess.run(["pgrep", "-x", "chrome"], capture_output=True).returncode == 0
        if not running:
            exe = next((b for b in ("google-chrome", "google-chrome-stable", "chromium") if shutil.which(b)), None)
            if exe:
                log.info("starting Chrome for the extension")
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(int(wait / 0.5)):
            if self.ws:
                return True
            await asyncio.sleep(0.5)
        return bool(self.ws)

    async def call(self, cmd: str, timeout: float = 20, **args) -> str:
        if not self.ws and not await self.ensure_connected():
            if SEEN.exists():
                return ("error: the Chrome extension isn't connected right now (Chrome may be starting or the "
                        "extension is turned off in chrome://extensions).")
            return ("error: the Chrome extension isn't connected. Open Chrome with the Clove Hands extension loaded "
                    "(chrome://extensions, Developer mode, Load unpacked, the chrome_extension folder).")
        i = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        try:
            await self.ws.send(json.dumps({"id": i, "cmd": cmd, **{k: v for k, v in args.items() if v is not None}}))
            r = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.pending.pop(i, None)
            return f"error: Chrome took more than {timeout:.0f}s to {cmd}"
        except (ConnectionError, websockets.ConnectionClosed) as e:
            return f"error: {e}"
        if r.get("ok"):
            return str(r.get("result"))
        err = str(r.get("error"))
        if "unknown command" in err or self.stale:
            err += (f" (the Chrome extension is out of date: v{self.ext_version or '?'} loaded, v{wanted_version()} on disk. "
                    "Open chrome://extensions and click the reload arrow on Clove Hands)")
        return f"error: {err}"


SEEN = config.STATE_DIR / "extension_seen.txt"     # the extension has connected at least once
SELF_RELOAD_WAIT_S = 20
RETRY_AFTER_S = 60                                 # after a failed wait for the extension, fail fast for this long                            # then, still old: ask the user to click reload
bridge = Bridge()


def open_in_chrome(url: str, new: bool = False) -> str | None:
    """For desktop.py (runs in a worker thread): open a URL through the extension so an already open tab is reused.
    Returns the extension's answer, or None when the extension isn't connected (the caller then launches Chrome)."""
    if not bridge.connected or bridge.loop is None:
        return None
    fut = asyncio.run_coroutine_threadsafe(bridge.call("open", timeout=15, url=url, new=True if new else None), bridge.loop)
    try:
        out = fut.result(timeout=18)
    except Exception:
        return None
    return None if out.startswith("error") else out

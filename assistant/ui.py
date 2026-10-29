"""The CLOVE window: a tiny local web server and the page it serves (ui/). It is shown in the CLOVE island's window
(its Assistant pages) when the island is installed, else in a Chrome app window.
Only this process talks to it (random port, per-run token, Origin check)."""
import json
import logging
import secrets
import shutil
import subprocess
import time
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.asyncio.server import serve

UI_DIR = Path(__file__).parent / "ui"
ASSETS = {"/clove.css": "text/css; charset=utf-8", "/clove.js": "text/javascript; charset=utf-8",
          "/fonts/Michroma-Regular.ttf": "font/ttf"}
logging.getLogger("websockets").setLevel(logging.CRITICAL)   # Chrome opens empty preconnect sockets
PROFILE = Path.home() / ".cache" / "clove-ui"
FEED_MAX = 150                     # conversation + tool rows replayed to a (re)connecting window
KEEP_LATEST = {"engine", "report", "route", "plan", "telemetry", "services", "workspace", "info", "window", "overview",
               "notice"}            # the latest notice (often "", i.e. cleared) wins over the replayed history


class UI:
    def __init__(self, on_message):
        self.token = secrets.token_urlsafe(16)
        self.on_message = on_message
        self.clients = set()
        self.ever_connected = False
        self.port = 0
        self.feed: list[dict] = []     # captions and activity rows, in the order they happened
        self.latest: dict[str, str] = {}   # the last message of each KEEP_LATEST type
        self.events: list[str] = []    # notices and toasts, for the Activity view

    async def start(self):
        self.server = await serve(self._handler, "127.0.0.1", 0, process_request=self._process)
        self.port = self.server.sockets[0].getsockname()[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def _process(self, conn, req):
        path, _, query = req.path.partition("?")
        if path in ASSETS:                    # static code, no data in it: no token needed
            f = UI_DIR / path[1:]
            resp = conn.respond(HTTPStatus.OK, f.read_bytes() if ASSETS[path].startswith("font/") else f.read_text())
            del resp.headers["Content-Type"]          # respond() sets text/plain; WebKit would go by that one
            resp.headers["Content-Type"] = ASSETS[path]
            resp.headers["Cache-Control"] = "no-store"
            return resp
        if f"t={self.token}" not in query.split("&"):
            return conn.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
        if path == "/ws":
            if req.headers.get("Origin") != f"http://127.0.0.1:{self.port}":
                return conn.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
            return None                       # proceed with websocket handshake
        if path == "/":
            resp = conn.respond(HTTPStatus.OK, (UI_DIR / "index.html").read_text())
            del resp.headers["Content-Type"]
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            resp.headers["Content-Security-Policy"] = ("default-src 'self'; connect-src 'self' ws://127.0.0.1:*; "
                                                       "style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            return resp
        return conn.respond(HTTPStatus.NOT_FOUND, "not found\n")

    async def _handler(self, ws):
        self.clients.add(ws)
        self.ever_connected = True
        try:
            await ws.send(json.dumps({"type": "reset"}))
            for m in self.feed:
                await ws.send(json.dumps(m if m["type"] != "caption" else {**m, "new": True}))
            for data in self.events[-40:] + list(self.latest.values()):
                await ws.send(data)
            async for raw in ws:
                try:
                    self.on_message(json.loads(raw))
                except ValueError:
                    pass
        finally:
            self.clients.discard(ws)

    def send(self, **msg):
        t = msg.get("type")
        if t in ("caption", "activity", "notice", "toast"):
            msg.setdefault("ts", time.time())
        if t == "caption":
            self._caption(msg)
        elif t == "activity":
            for i, m in enumerate(self.feed):
                if m["type"] == "activity" and m["id"] == msg["id"]:
                    self.feed[i] = {**m, **msg, "ts": m["ts"], "updated": msg["ts"]}
                    break
            else:
                self.feed.append(dict(msg))
            self.feed = self.feed[-FEED_MAX:]
        data = json.dumps(msg)
        if t in KEEP_LATEST:
            self.latest[t] = data
        if t in ("notice", "toast") and msg.get("text"):
            self.events = (self.events + [data])[-80:]
        if self.clients:
            websockets.broadcast(self.clients, data)

    def _caption(self, msg: dict):
        """'new' starts a message; otherwise the text continues that speaker's latest message."""
        who = msg["who"]
        if not msg.get("new"):
            for m in reversed(self.feed):
                if m["type"] == "caption" and m["who"] == who:
                    m["text"] += msg["text"]
                    return
        self.feed.append({"type": "caption", "who": who, "text": msg["text"], "ts": msg["ts"]})
        self.feed = self.feed[-FEED_MAX:]


def open_window(url: str, compact: bool = False):
    """The CLOVE island's window on its Assistant page (it finds this window's address itself, in clove.url).
    The compact companion, or no island: a Chrome --app window with its own profile, so it never touches your
    normal Chrome windows."""
    island = shutil.which("clove-island")
    if island and not compact:
        subprocess.Popen([island, "--page", "assistant"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    if not chrome:
        subprocess.Popen(["xdg-open", url], start_new_session=True)
        return
    PROFILE.mkdir(parents=True, exist_ok=True)
    size = "380,560" if compact else "1280,800"
    subprocess.Popen([chrome, f"--app={url}", f"--window-size={size}", f"--user-data-dir={PROFILE}",
                      "--no-first-run", "--no-default-browser-check", "--class=Clove"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)

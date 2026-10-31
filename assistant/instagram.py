"""Instagram DMs through Instagram's official API (the Instagram API with Instagram Login), no browser and no password.

  - Meta delivers each new DM to a webhook here (a public address: a Cloudflare tunnel hostname pointing at
    IG_WEBHOOK_PORT on this PC). Every delivery is checked against the app secret (X-Hub-Signature-256), so
    nobody else can feed CLOVE messages.
  - The sender's name and @username come from the API (allowed once they have messaged him).
  - Each message goes to notifications.py like any notification: announced, the notch banner, auto-reply,
    Telegram while he's away.
  - Replies go out through the API (within Instagram's 24-hour window after their last message).

Setup (his Instagram must be a free Professional account, linked to his own Meta app): .env gets IG_ACCESS_TOKEN
(the long-lived token from the app dashboard), IG_APP_SECRET and IG_VERIFY_TOKEN (any phrase, typed again in the
dashboard's webhook setup). The token lasts 60 days; CLOVE refreshes it every few weeks and keeps the new one in
~/.local/state/clove/instagram_token (readable only by him).
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import config

log = logging.getLogger("clove.instagram")
API = "https://graph.instagram.com/v26.0"
MAX_BODY = 1 << 20
TOKEN_FILE = config.STATE_DIR / "instagram_token"
REFRESH_EVERY_S = 20 * 24 * 3600


def token() -> str:
    try:
        saved = TOKEN_FILE.read_text().strip()
        if saved:
            return saved
    except OSError:
        pass
    return config.IG_ACCESS_TOKEN


def signature_ok(body: bytes, header: str, secret: str) -> bool:
    """Meta signs every delivery: X-Hub-Signature-256 = "sha256=" + HMAC-SHA256(app secret, raw body)."""
    if not secret or not header.startswith("sha256="):
        return False
    want = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header[7:].strip())


def messages_in(payload: dict) -> list[dict]:
    """The new DMs in one delivery: [{sender, text, mid}]. His own messages (echoes) and reactions are left out."""
    out = []
    if payload.get("object") != "instagram":
        return out
    for entry in payload.get("entry") or []:
        for ev in entry.get("messaging") or []:
            msg = ev.get("message") or {}
            sender = str((ev.get("sender") or {}).get("id") or "")
            if not msg or msg.get("is_echo") or msg.get("is_deleted") or not sender:
                continue
            text = str(msg.get("text") or "")
            if not text and msg.get("attachments"):
                kind = str((msg["attachments"][0] or {}).get("type") or "attachment")
                text = {"image": "sent a photo", "video": "sent a video", "audio": "sent a voice message",
                        "share": "shared a post", "story_mention": "mentioned you in their story",
                        "ig_reel": "sent a reel"}.get(kind, f"sent {kind}")
            if text:
                out.append({"sender": sender, "text": text[:1000], "mid": str(msg.get("mid") or "")})
    return out


def _get(path: str, **params) -> dict:
    params["access_token"] = token()
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        return json.loads(r.read().decode())


def profile(igsid: str) -> dict:
    """Their name and @username (Instagram allows it once they have messaged him)."""
    try:
        return _get(igsid, fields="name,username")
    except Exception as e:
        log.info("no profile for %s: %s", igsid, e)
        return {}


def send(igsid: str, text: str) -> bool:
    """A reply in their chat. Only inside Instagram's 24-hour window after their last message."""
    body = json.dumps({"recipient": {"id": igsid}, "message": {"text": text[:1000]}}).encode()
    req = urllib.request.Request(f"{API}/me/messages", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read().decode()).get("message_id"))
    except Exception as e:
        log.warning("Instagram reply not sent: %s", e)
        return False


def refresh_token() -> bool:
    """Swaps the long-lived token for a new 60-day one, and keeps it."""
    try:
        url = f"https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={token()}"
        with urllib.request.urlopen(url, timeout=15) as r:
            new = json.loads(r.read().decode()).get("access_token", "")
    except Exception as e:
        log.warning("Instagram token not refreshed: %s", e)
        return False
    if not new:
        return False
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(new)
    log.info("Instagram token refreshed")
    return True


class Instagram:
    """The webhook (a tiny HTTP server) and the bridge to notifications.py."""

    def __init__(self, a):
        self.a = a
        self.people: dict[str, dict] = {}         # igsid -> {name, username}
        self.by_name: dict[str, str] = {}         # "name"/"@username" -> igsid, so a reply finds them
        self.seen: set[str] = set()

    def enabled(self) -> bool:
        return bool(token() and config.IG_APP_SECRET and config.IG_VERIFY_TOKEN)

    async def run(self):
        if not self.enabled():
            return
        server = await asyncio.start_server(self._client, config.IG_WEBHOOK_HOST, config.IG_WEBHOOK_PORT)
        log.info("Instagram webhook on %s:%d", config.IG_WEBHOOK_HOST, config.IG_WEBHOOK_PORT)
        async with server:
            while True:
                await asyncio.sleep(24 * 3600)
                try:
                    age = time.time() - TOKEN_FILE.stat().st_mtime
                except OSError:
                    age = REFRESH_EVERY_S
                if age >= REFRESH_EVERY_S:
                    await asyncio.to_thread(refresh_token)

    # ---- HTTP --------------------------------------------------------------------------------------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            status, body = await asyncio.wait_for(self._handle(reader), 15)
        except Exception as e:
            log.info("webhook request refused: %s", e)
            status, body = 400, b"bad request"
        writer.write(f"HTTP/1.1 {status} {'OK' if status == 200 else 'Error'}\r\nContent-Type: text/plain\r\n"
                     f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        try:
            await writer.drain()
        finally:
            writer.close()

    async def _handle(self, reader) -> tuple[int, bytes]:
        line = (await reader.readline()).decode("latin-1").strip()
        method, target, _ = (line.split(" ") + ["", "", ""])[:3]
        headers = {}
        while (h := (await reader.readline()).decode("latin-1")) not in ("\r\n", "\n", ""):
            k, _, v = h.partition(":")
            headers[k.strip().lower()] = v.strip()
        path, _, query = target.partition("?")
        if path != "/instagram":
            return 404, b"not here"
        if method == "GET":                               # Meta checks the address once, when it's set up
            q = urllib.parse.parse_qs(query)
            if q.get("hub.mode", [""])[0] == "subscribe" and hmac.compare_digest(
                    q.get("hub.verify_token", [""])[0], config.IG_VERIFY_TOKEN):
                return 200, q.get("hub.challenge", [""])[0].encode()
            return 403, b"wrong verify token"
        if method != "POST":
            return 405, b"no"
        size = int(headers.get("content-length") or 0)
        if size <= 0 or size > MAX_BODY:
            return 413, b"too big"
        body = await reader.readexactly(size)
        if not signature_ok(body, headers.get("x-hub-signature-256", ""), config.IG_APP_SECRET):
            log.warning("Instagram webhook: a delivery with a bad signature was refused")
            return 403, b"bad signature"
        asyncio.create_task(self.delivered(json.loads(body)))
        return 200, b"ok"

    # ---- messages ----------------------------------------------------------------------------------
    async def delivered(self, payload: dict):
        from notifications import Note
        for m in messages_in(payload):
            if m["mid"] and m["mid"] in self.seen:
                continue
            self.seen.add(m["mid"])
            who = self.people.get(m["sender"])
            if who is None:
                who = await asyncio.to_thread(profile, m["sender"])
                self.people[m["sender"]] = who
            name, username = str(who.get("name") or ""), str(who.get("username") or "")
            title = name or (f"@{username}" if username else "Someone on Instagram")
            for key in (name, username, f"@{username}" if username else ""):
                if key:
                    self.by_name[key.lower()] = m["sender"]
            note = Note(app="Instagram", title=title, body=m["text"], platform="Instagram")
            note.handle = f"@{username}" if username and username != title.lstrip("@") else ""
            note.igsid = m["sender"]
            log.info("Instagram message from %s", note.who)
            self.a.messages.seen_note(note)

    def reply(self, who: str, text: str) -> str:
        """For the brain's tool: reply to someone who messaged him, by name or @username."""
        key = who.strip().lower()
        igsid = self.by_name.get(key) or self.by_name.get(key.lstrip("@")) or self.by_name.get("@" + key.lstrip("@"))
        if not igsid:
            return f"error: no Instagram message from {who} since CLOVE started, so no chat to reply in"
        return f"sent to {who} on Instagram" if send(igsid, text) else \
            "error: Instagram didn't take it (more than 24 hours since their last message, or the token expired)"

"""Outbound mobile calls: Clove calls the user's phone with updates and converses.

Uses Twilio Programmable Voice. Twilio handles TTS and speech recognition; Clove
provides TwiML via a small webhook server and drives the conversation with its LLM.

Config (env or .env):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, USER_MOBILE_NUMBER,
  CLOVE_WEBHOOK_URL (public URL Twilio can reach, e.g. https://clove.redclove.space)
"""
import asyncio
import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

log = logging.getLogger("clove.mobile_outbound")

STATE: dict[str, Any] = {"pending_update": "", "history": [], "active": False}


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    if not v:
        try:
            import config
            v = getattr(config, name, default) or default
        except Exception:
            pass
    return v


def configured() -> bool:
    return all(_env(n) for n in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                                 "TWILIO_FROM_NUMBER", "USER_MOBILE_NUMBER",
                                 "CLOVE_WEBHOOK_URL"))


def _twilio_request(path: str, data: dict) -> dict:
    sid = _env("TWILIO_ACCOUNT_SID")
    token = _env("TWILIO_AUTH_TOKEN")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/{path}"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    import base64
    cred = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {cred}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def call_me(update: str = "", message: str = "") -> str:
    if not configured():
        return ("error: Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                "TWILIO_FROM_NUMBER, USER_MOBILE_NUMBER, CLOVE_WEBHOOK_URL in .env")
    STATE["pending_update"] = update or message or "Clove has an update for you."
    STATE["history"] = []
    STATE["active"] = True
    try:
        start_webhook(8765)
    except Exception:
        pass
    webhook = _env("CLOVE_WEBHOOK_URL").rstrip("/") + "/twilio/voice"
    res = _twilio_request("Calls.json", {
        "To": _env("USER_MOBILE_NUMBER"),
        "From": _env("TWILIO_FROM_NUMBER"),
        "Url": webhook,
        "Method": "POST",
    })
    if "error" in res:
        STATE["active"] = False
        return f"error: {res['error']}"
    return f"Calling you now (sid={res.get('sid')}). I'll speak the update and listen for your reply."


def hangup() -> str:
    STATE["active"] = False
    STATE["history"] = []
    return "Call state cleared. (Hang up on the phone to end the call.)"


def _twiml(say: str, gather: bool = True) -> str:
    s = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    s += f"<Say>{_escape(say)}</Say>"
    if gather:
        s += ('<Gather input="speech" timeout="6" speechTimeout="auto" action="/twilio/gather" method="POST">'
              '<Say> </Say></Gather>')
        s += "<Say>I didn't catch that. Goodbye.</Say>"
    s += "</Response>"
    return s


def _escape(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def _llm_reply(user_text: str) -> str:
    # Use best available CLI to generate a reply
    try:
        import cli_adapter, asyncio
        prompt = ("You are Clove, a voice assistant calling the user on their phone. "
                  "Reply concisely (1-3 sentences, spoken style). User said: " + user_text)
        r = asyncio.run(cli_adapter.run_task(prompt, cli=cli_adapter.best_cli(), timeout=60))
        return r.output if r.ok else "Sorry, I had trouble thinking. Try again."
    except Exception as e:
        return "Sorry, I had trouble thinking."


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else ""
        params = urllib.parse.parse_qs(body)
        path = self.path.split("?")[0]
        if path == "/twilio/voice":
            msg = STATE.get("pending_update", "Clove has an update.")
            STATE["pending_update"] = ""
            twiml = _twiml(msg, gather=True)
        elif path == "/twilio/gather":
            speech = params.get("SpeechResult", [""])[0]
            if speech:
                STATE["history"].append({"role": "user", "content": speech})
                reply = _llm_reply(speech)
                STATE["history"].append({"role": "assistant", "content": reply})
                twiml = _twiml(reply, gather=True)
            else:
                twiml = _twiml("I didn't catch that. Goodbye.", gather=False)
        else:
            twiml = _twiml("Hello.", gather=False)
        data = twiml.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


_server: HTTPServer | None = None
_thread: threading.Thread | None = None


def start_webhook(port: int = 8765) -> str:
    global _server, _thread
    if _server is not None:
        return "webhook already running"
    _server = HTTPServer(("0.0.0.0", port), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    return f"webhook listening on :{port}"


def stop_webhook() -> str:
    global _server, _thread
    if _server is None:
        return "not running"
    _server.shutdown()
    _server = None
    _thread = None
    return "webhook stopped"


def call_me_free(update: str = "") -> str:
    """Free alternative: create a Jitsi Meet room, open it in Chrome, and share the link.

    No Twilio/SIP needed. User joins the same room on their phone browser to talk.
    Optionally sends the link via Telegram if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set.
    """
    import secrets, subprocess, webbrowser
    room = "clove-" + secrets.token_hex(6)
    url = f"https://meet.jit.si/{room}"
    # open in Chrome on this machine so Clove joins the call
    try:
        from desktop import chrome_argv
        subprocess.Popen(chrome_argv("--new-window", url),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    # optional telegram notify
    tg_token = _env("TELEGRAM_BOT_TOKEN")
    tg_chat = _env("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        try:
            data = urllib.parse.urlencode({"chat_id": tg_chat, "text": f"Clove is calling: {url}\n{update}"}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{tg_token}/sendMessage", data=data)
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.warning("telegram notify failed: %s", e)
    msg = f"Opened Jitsi room {url}. Join it on your phone to talk. {update}".strip()
    return msg

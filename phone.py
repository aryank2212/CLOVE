"""Talk to Clove from your phone over Telegram: send a text or a voice note to your bot, Clove does it on the PC and
texts back. Voice notes are written by local Whisper (nothing extra goes to the cloud). Only messages from
TELEGRAM_CHAT_ID are read; everyone else is ignored. Background jobs started from the phone text their result too.

Turn on with PHONE_INBOX=on (needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID). Clove answers with a text-only copy
of the hybrid brain, so approvals work by replying "yes" in the chat.
"""
import asyncio
import json
import logging
import subprocess
import tempfile
import urllib.parse
import urllib.request

import config

log = logging.getLogger("clove.phone")
API = "https://api.telegram.org/bot{token}/{method}"
OFFSET_FILE = config.STATE_DIR / "telegram_offset.txt"


def _api(method: str, timeout: float = 40, **params) -> dict:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(text: str) -> None:
    for i in range(0, len(text), 4000):
        _api("sendMessage", 20, chat_id=config.TELEGRAM_CHAT_ID, text=text[i:i + 4000])


def _voice_pcm(file_id: str) -> bytes:
    path = _api("getFile", 20, file_id=file_id)["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}"
    with tempfile.NamedTemporaryFile(suffix=".oga") as f:
        with urllib.request.urlopen(url, timeout=60) as r:
            f.write(r.read())
        f.flush()
        p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", f.name, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True, timeout=60)
    return p.stdout


class PhoneInbox:
    def __init__(self, a):
        self.a = a
        self.brain = None
        self.stt = None

    def enabled(self) -> bool:
        return config.PHONE_INBOX and bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID and self.a.client)

    def _make_brain(self):
        from brain_hybrid import HybridBrain
        from prompt import system_prompt
        b = HybridBrain(self.a)
        b.system = system_prompt("hybrid") + ("\n\nThis request came by TEXT from his phone (Telegram), not by voice: he may "
                                      "be away from the PC. Reply in short plain text. Screen tools see the PC screen, "
                                      "not his phone.")
        b.out = []
        b.say = lambda s: b.out.append(s.strip())
        b.caption = lambda *x, **k: None
        return b

    async def run(self):
        if not self.enabled():
            return
        try:
            offset = int(OFFSET_FILE.read_text())
        except (OSError, ValueError):
            offset = 0
        log.info("phone inbox on (Telegram)")
        while True:
            try:
                r = await asyncio.to_thread(_api, "getUpdates", 45, offset=offset, timeout=30,
                                            allowed_updates='["message"]')
            except Exception as e:
                log.debug("telegram poll: %s", e)
                await asyncio.sleep(15)
                continue
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                OFFSET_FILE.write_text(str(offset))
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                    continue                                   # not him: ignore without a reply
                try:
                    await self._handle(m)
                except Exception as e:
                    log.exception("phone message failed")
                    await asyncio.to_thread(send, f"Sorry, that failed: {str(e)[:200]}")

    async def _handle(self, m: dict):
        text = (m.get("text") or m.get("caption") or "").strip()
        if not text and (m.get("voice") or m.get("audio")):
            pcm = await asyncio.to_thread(_voice_pcm, (m.get("voice") or m.get("audio"))["file_id"])
            text = await asyncio.to_thread(self._transcribe, pcm)
            if text:
                await asyncio.to_thread(send, f"🎙 \"{text}\"")
        if not text:
            return
        log.info("from phone: %r", text[:120])
        a = self.a
        a.tools.on_user_words(text)                           # a "yes" approves a pending plan
        if self.brain is None:
            self.brain = self._make_brain()
        b, before = self.brain, set(a.jobs.jobs)
        b.out = []
        await b._turn(text)
        reply = " ".join(x for x in b.out if x) or "Done."
        for jid in set(a.jobs.jobs) - before:                 # jobs it started text their result when they finish
            a.jobs.jobs[jid].meta["phone"] = True
        await asyncio.to_thread(send, reply)

    def _transcribe(self, pcm: bytes) -> str:
        brain = self.a.brain
        stt = getattr(brain, "stt", None) or self.stt
        if stt is None:
            from prompt import vocabulary
            from stt import STT
            stt = self.stt = STT(vocabulary())
        return stt.transcribe(pcm).strip()

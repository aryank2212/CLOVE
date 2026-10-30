"""CLOVE picks up his WhatsApp calls (Preferences › "Answer my WhatsApp calls", off by default; he asked for it).

Every few seconds it looks at WhatsApp Web in Chrome. When a call is ringing there, the call agent (call_agent.py)
answers it: it says it is CLOVE, his AI assistant, takes a message, and keeps talking for as long as the caller
wants (it never hangs up on them first). Money, codes, private details and commitments are never handled on the
call; they go back to him, as on every CLOVE call.

When the call is over he gets the summary on Telegram from CLOVE's own bot (CLOVE_TELEGRAM_BOT_TOKEN), and hears
it at the PC as with any call.
"""
import asyncio
import logging
import time

import config

log = logging.getLogger("clove.call_watch")
POLL_S = 3

MISSION = """Someone is calling {owner} on WhatsApp and you are answering for him. Greet them warmly, say you are \
CLOVE, {owner}'s AI assistant, and that he can't take the call right now. Find out who is calling (if you don't \
know) and what it's about, and offer to pass a message on. Note their name, the reason, anything urgent, and when \
and how they'd like {owner} to get back to them.

If they want to keep talking, keep the conversation going naturally for as long as they like: answer what you can \
in general terms, be good company, and never be the one to end the call. Only say goodbye and end once they are \
done or say goodbye themselves. Never agree to anything, promise anything, or share {owner}'s whereabouts, plans, \
numbers, money or codes; say you'll pass it on to him."""


class CallWatch:
    def __init__(self, a):
        self.a = a
        self.answered_at = 0.0

    def on(self) -> bool:
        return bool(self.a.dashboard.prefs.get("answercalls", False))

    async def run(self):
        while True:
            await asyncio.sleep(POLL_S)
            try:
                await self.check()
            except Exception as e:
                log.warning("call watch: %s", e)

    async def check(self):
        a = self.a
        if not self.on() or a.calls.active or time.monotonic() - self.answered_at < 20:
            return
        from browser_bridge import bridge
        if not bridge.connected:
            return
        from call_agent import parse_state
        out = await bridge.call("call_state", timeout=8, platform="whatsapp")
        if parse_state(out).get("phase") != "incoming":
            return
        who = self.caller()
        log.info("incoming WhatsApp call from %s: answering", who or "an unknown caller")
        self.answered_at = time.monotonic()
        owner = config.USER_NAME or "the owner"
        started = await a.calls.start("whatsapp", who or "the caller", MISSION.format(owner=owner), incoming=True)
        if started.startswith("error") or "already in progress" in started:
            log.warning("could not answer the call: %s", started)
            return
        asyncio.create_task(self._after(who))

    def caller(self) -> str:
        """Who is calling: the newest WhatsApp notification of the last half minute (WhatsApp Web names the caller)."""
        messages = getattr(self.a, "messages", None)
        if messages is None:
            return ""
        now = time.time()
        for n in reversed(messages.recent):
            if now - n.at > 30:
                break
            if n.platform == "WhatsApp" and n.title:
                return n.title
        return ""

    async def _after(self, who: str):
        """Wait for the call to end, then send him the summary on Telegram."""
        calls = self.a.calls
        while calls.task is not None and not calls.task.done():
            await asyncio.sleep(2)
        report = getattr(calls, "last_report", "") or "The call ended."
        text = f"📞 CLOVE answered a WhatsApp call from {who or 'someone'}.\n\n{report}"
        token = config.CLOVE_TELEGRAM_BOT_TOKEN
        if not (token and config.TELEGRAM_CHAT_ID):
            log.info("call summary not sent to Telegram: CLOVE has no bot of its own (CLOVE_TELEGRAM_BOT_TOKEN)")
            return
        import phone
        try:
            await asyncio.to_thread(phone.send, text[:3500], token)
            log.info("call summary sent to Telegram")
        except Exception as e:
            log.warning("could not send the call summary to Telegram: %s", e)

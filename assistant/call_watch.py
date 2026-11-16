"""CLOVE picks up his calls (Preferences › "Answer my calls", off by default; he asked for it).

Every few seconds it looks at WhatsApp Web in Chrome, and at his phone when it is connected to the PC over Bluetooth
(cell_call.py: his normal cellular calls). When a call is ringing, the call agent (call_agent.py) answers it: it
says it is CLOVE, his AI assistant, takes a message, and keeps talking for as long as the caller wants (it never
hangs up on them first). Money, codes, private details and commitments are never handled on the
call; they go back to him, as on every CLOVE call.

When the call is over he gets the summary on Telegram from CLOVE's own bot (CLOVE_TELEGRAM_BOT_TOKEN), and hears
it at the PC as with any call.
"""
import asyncio
import logging
import time

import config

log = logging.getLogger("clove.call_watch")
POLL_S = 3                            # WhatsApp Web (asks Chrome)
PHONE_POLL_S = 1                      # the phone line (a quick bus call): a ringing call is caught at once
LIVE = ("incoming", "waiting", "dialing", "alerting", "active", "held")

MISSION = """Someone is calling {owner} on {where} and you are answering for him. Greet them warmly, say you are \
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
        self.seen: dict[str, str] = {}       # phone call path -> last state, to log every change
        self.quieted = False                 # the main assistant was muted for a phone call it isn't handling
        self.was_muted = False

    def on(self) -> bool:
        return bool(self.a.dashboard.prefs.get("answercalls", False))

    async def run(self):
        n = 0
        while True:
            await asyncio.sleep(PHONE_POLL_S)
            n += 1
            try:
                import cell_call
                now = await asyncio.to_thread(cell_call.calls)
                self.phone_changed(now)
                if n % POLL_S == 0 or any(c["state"] == "incoming" for c in now):
                    await self.check(now)
            except Exception as e:
                log.warning("call watch: %s", e)

    def phone_changed(self, now: list[dict]):
        """Log every change on the phone line, and keep the main assistant quiet during a phone call that its call
        agent isn't handling: the call's sound comes out of the PC, and it must not hear the caller and answer them."""
        states = {c["path"]: c["state"] for c in now}
        notch = getattr(self.a, "notch", None)
        for c in now:
            path, st = c["path"], c["state"]
            if self.seen.get(path) != st:
                log.info("phone line: %s %s", path.rsplit("/", 1)[-1], st)
                if st == "incoming" and notch is not None:
                    notch.notice("Phone", "ringing", c["name"] or c["number"] or "Unknown number")
        for path in set(self.seen) - set(states):
            log.info("phone line: %s ended", path.rsplit("/", 1)[-1])
        self.seen = states
        a = self.a
        live = any(st in LIVE for st in states.values())
        theirs = live and not a.calls.active           # a call he takes himself (or one ringing before CLOVE picks up)
        if theirs and not self.quieted:
            self.quieted, self.was_muted = True, bool(a.muted)
            a.set_muted(True)
            log.info("phone call on the line: the assistant stops listening until it ends")
        elif not theirs and self.quieted:
            self.quieted = False
            a.set_muted(self.was_muted)
    async def check(self, phone: list[dict] | None = None):
        a = self.a
        if not self.on() or a.calls.active or time.monotonic() - self.answered_at < 20:
            return
        import cell_call
        ring = next((c for c in phone if c["state"] == "incoming"), None) if phone is not None \
            else await asyncio.to_thread(cell_call.ringing)
        if ring:
            who = ring["name"] or ring["number"] or "an unknown number"
            log.info("incoming phone call from %s: answering", who)
            self.answered_at = time.monotonic()
            owner = config.USER_NAME or "the owner"
            started = await a.calls.start_phone(ring, who, MISSION.format(owner=owner, where="his phone"))
            if started.startswith("error") or "already in progress" in started:
                log.warning("could not answer the phone call: %s", started)
                return
            if getattr(a, "notch", None) is not None:
                a.notch.notice("Phone", "call", who, "CLOVE is talking to them for you.")
            asyncio.create_task(self._after(who, "phone"))
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
        started = await a.calls.start("whatsapp", who or "the caller", MISSION.format(owner=owner, where="WhatsApp"),
                                      incoming=True)
        if started.startswith("error") or "already in progress" in started:
            log.warning("could not answer the call: %s", started)
            return
        if getattr(a, "notch", None) is not None:
            a.notch.notice("WhatsApp", "call", who or "WhatsApp call", "CLOVE is talking to them for you.")
        asyncio.create_task(self._after(who, "WhatsApp"))

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

    async def _after(self, who: str, where: str = "WhatsApp"):
        """Wait for the call to end, then send him the summary on Telegram."""
        calls = self.a.calls
        while calls.task is not None and not calls.task.done():
            await asyncio.sleep(2)
        report = getattr(calls, "last_report", "") or "The call ended."
        notch = getattr(self.a, "notch", None)
        if notch is not None:
            notch.notice("Phone" if where == "phone" else "WhatsApp", "ended", who or "Call", report)
        what = "a phone call" if where == "phone" else "a WhatsApp call"
        text = f"📞 CLOVE answered {what} from {who or 'someone'}.\n\n{report}"
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

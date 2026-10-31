"""Focus mode: "focus for 50 minutes". Clove holds back everything that isn't urgent (finished jobs, narration),
nudges him once if a distracting site or app takes the screen, and at the end says what came in meanwhile.
Ask "how long is left?" any time; "stop focus" ends it early."""
import asyncio
import logging
import re
import time

import config

log = logging.getLogger("clove.focus")
NUDGE_GAP_S = 180


class Focus:
    def __init__(self, a):
        self.a = a
        self.until = 0.0
        self.started = 0.0
        self.held: list = []                     # jobs that finished during the session
        self.task: asyncio.Task | None = None
        self.last_nudge = 0.0
        self.block = re.compile("|".join(re.escape(d) for d in config.FOCUS_DISTRACTIONS), re.I) \
            if config.FOCUS_DISTRACTIONS else None

    @property
    def active(self) -> bool:
        return time.time() < self.until

    def remaining(self) -> str:
        if not self.active:
            return "off"
        return f"{int((self.until - time.time()) // 60) + 1} min left"

    def start(self, minutes: float) -> str:
        minutes = max(1.0, min(float(minutes or 50), 240.0))
        self.started, self.until, self.held = time.time(), time.time() + minutes * 60, []
        if self.task:
            self.task.cancel()
        self.task = asyncio.get_running_loop().create_task(self._watch())
        log.info("focus for %d min", minutes)
        return (f"Focus mode for {int(minutes)} minutes: I'll hold everything that isn't urgent and tell you "
                "at the end what came in.")

    def stop(self, early: bool = True) -> str:
        if not self.active and not self.held:
            return "Focus mode isn't on."
        mins = int((time.time() - self.started) / 60)
        self.until = 0.0
        if self.task and early:
            self.task.cancel()
        held, self.held = self.held, []
        for job in held:
            asyncio.get_running_loop().create_task(self.a.deliver_job(job))
        news = f" {len(held)} things finished meanwhile; I'll tell you about them now." if held else " Nothing came in meanwhile."
        return f"Focus session over after {mins} minutes.{news}"

    def hold(self, job) -> bool:
        """Called for a finished job: True means it waits until the session ends (failures still get through)."""
        if not self.active or job.status == "failed":
            return False
        self.held.append(job)
        return True

    async def _watch(self):
        try:
            while self.active:
                await asyncio.sleep(10)
                if self.block and time.time() - self.last_nudge > NUDGE_GAP_S:
                    where = self._screen()
                    hit = self.block.search(where) if where else None
                    if hit:
                        self.last_nudge = time.time()
                        self.a.wake.wake("focus nudge")
                        await self.a.notify(
                            f"[Focus mode - a system note] He is in a focus session ({self.remaining()}) but "
                            f"{hit.group(0)} is on his screen. In ONE friendly sentence of at most 12 words, nudge "
                            "him back to work. Do not call tools.")
            import sounds
            sounds.play(self.a, "done")
            self.a.wake.wake("focus over")
            await self.a.notify(f"[Focus mode - a system note] The focus session has ended. Tell him: {self.stop(early=False)}")
        except asyncio.CancelledError:
            pass

    def _screen(self) -> str:
        parts = []
        try:
            from browser_bridge import bridge
            parts.append(bridge.screen_note() or "")
        except Exception:
            pass
        try:
            import deskctx
            w = deskctx.current()
            parts.append(f'{w.get("app", "")} {w.get("title", "")}')
        except Exception:
            pass
        return " ".join(parts)

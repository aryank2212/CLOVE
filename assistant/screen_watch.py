"""Proactive screen watch: background loop that alerts on conditions."""
import asyncio
import logging
import time
from typing import Callable

log = logging.getLogger("clove.screen_watch")

class ScreenWatcher:
    def __init__(self, look_fn, speak_fn):
        self.look_fn = look_fn  # async (question) -> str
        self.speak_fn = speak_fn  # async (text) -> None
        self.conditions: list[str] = []
        self.running = False
        self._task = None

    def add(self, condition: str) -> str:
        self.conditions.append(condition)
        return f"Watching for: {condition}"

    def clear(self) -> str:
        self.conditions.clear()
        return "Screen watch cleared."

    async def _loop(self):
        self.running = True
        while self.running and self.conditions:
            try:
                q = "Is any of this true on screen: " + "; ".join(self.conditions) + "? Answer YES/NO plus one short line."
                ans = await self.look_fn(q)
                if ans and ans.strip().upper().startswith("YES"):
                    await self.speak_fn("Screen alert: " + ans.strip()[:200])
                    await asyncio.sleep(60)  # cooldown
                await asyncio.sleep(8)
            except Exception as e:
                log.warning("screen_watch error: %s", e)
                await asyncio.sleep(10)

    def start(self):
        if self._task and not self._task.done():
            return "already watching"
        self._task = asyncio.ensure_future(self._loop())
        return "screen watch started"

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
        return "screen watch stopped"

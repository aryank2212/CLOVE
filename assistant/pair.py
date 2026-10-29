"""Pair-programming mode: while it is on, Clove quietly watches the git diff of the project he is working in (the
focused terminal's folder, or the one he names) and speaks up rarely, only about something that looks clearly
wrong: a bug, an infinite loop, a leaked secret. It reads the diff with the cheap Flash-Lite model every few
minutes and only when the diff has changed; most checks end in silence."""
import asyncio
import hashlib
import logging
import subprocess
import time
from pathlib import Path

from google.genai import types

import config

log = logging.getLogger("clove.pair")
EVERY_S = 150
MIN_GAP_S = 300                     # never speak up more often than this
REVIEW = ("You are a senior engineer pair-programming by voice. Below is the developer's uncommitted git diff. If, and "
          "only if, it contains something clearly wrong (a bug, an off-by-one, a loop that never ends, a crash, a leaked "
          "secret or password, an obvious security hole), reply with ONE short spoken sentence naming the file and the "
          "problem. Otherwise reply with exactly: OK\n\n")


class Pair:
    def __init__(self, a):
        self.a = a
        self.task: asyncio.Task | None = None
        self.folder = ""
        self.last_hash = ""
        self.last_spoke = 0.0
        self.said: set[str] = set()

    @property
    def on(self) -> bool:
        return bool(self.task and not self.task.done())

    def start(self, folder: str = "") -> str:
        import deskctx
        folder = folder or deskctx.current().get("folder", "")
        folder = str(Path(folder).expanduser()) if folder else ""
        if not folder or subprocess.run(["git", "-C", folder, "rev-parse"], capture_output=True).returncode != 0:
            return "error: tell me which project folder (a git repository) to watch, or focus its terminal first"
        self.folder, self.last_hash = folder, ""
        if self.task:
            self.task.cancel()
        self.task = asyncio.get_running_loop().create_task(self._watch())
        return f"Pair mode on for {folder.replace(str(Path.home()), '~')}: I'll speak up only if something looks wrong."

    def stop(self) -> str:
        if not self.on:
            return "Pair mode isn't on."
        self.task.cancel()
        return "Pair mode off."

    async def _watch(self):
        try:
            while True:
                await asyncio.sleep(EVERY_S)
                if self.a.focus.active or self.a.dictation.on:
                    continue
                diff = await asyncio.to_thread(lambda: subprocess.run(
                    ["git", "-C", self.folder, "diff", "--no-color", "-U2"], capture_output=True, text=True).stdout)
                h = hashlib.md5(diff.encode()).hexdigest()
                if not diff.strip() or h == self.last_hash or time.time() - self.last_spoke < MIN_GAP_S:
                    continue
                self.last_hash = h
                r = await self.a.client.aio.models.generate_content(
                    model=config.VISION_MODELS[0], contents=REVIEW + diff[-24000:],
                    config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=80))
                note = (r.text or "").strip()
                if not note or note.upper().startswith("OK") or note in self.said:
                    continue
                self.said.add(note)
                self.last_spoke = time.time()
                log.info("pair: %s", note)
                self.a.wake.wake("pair")
                await self.a.notify(f"[Pair-programming note - a system note] Tell him briefly, in your words: {note} "
                                    "Do not call tools.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("pair mode stopped: %s", e)

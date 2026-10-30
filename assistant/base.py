"""The shared assistant: mic gating, the window, tools/plans/jobs/routines, reminders, the status orb, and the
switch between brains (Gemini in the cloud, Qwen on this PC). A brain only implements how speech reaches a model
and back, so everything running (jobs, memory, cursor) survives a switch."""
import asyncio
import collections
import logging
import re
import time

import config
import memory
import screen
from audio import pick_route
from daymem import DayMemory
from jobs import Job, Jobs
from routines import Routines
from tools import LABELS as LABELS_NOTCH, Toolbox, describe, is_failure

log = logging.getLogger("clove")
QUIET_TOOLS = {"update_step", "record_approval", "job_status"}     # shown in the plan card, not as activity rows


BRAIN_NAMES = {
    # Whisper spells "Qwen" many ways: Quen, QN, Gwen, Quinn, Kwan, Q W E N...
    "qwen": r"(?:qwen|quen|kwen|gwen|queen|chwen|qn|q n|q w e n|quin|quinn|kwan|cuen|kuen|coin|local|offline|on[- ]device)",
    "hybrid": r"(?:hybrid|high bread|hi bread|saver|saving|free mode|cheap mode|eco mode)",
    "gemini": r"(?:gemini|jemini|gemin[iy]|jiminy|cloud|online)",
    "clove": r"(?:clove|male voice|male)",
    "rose": r"(?:rose|female voice|female)",
}
SWITCH_VERB = r"(?:switch|change|swap|move|go|come|get|set)(?: back)?(?: over)?(?: to| with| into| onto)?"
SLEEP = re.compile(r"^\W*(?:(?:ok(?:ay)?|thanks?|thank you|cool)\W+)?(?:clove|rose)?\W*(?:go to sleep|sleep now|stop listening|"
                   r"that'?s all(?: for now)?|you can sleep|go quiet)\W*$", re.I)
STATE_FILE = config.STATE_DIR / "brain.txt"
VOICE_FILE = config.STATE_DIR / "voice.txt"


def parse_switch(text: str) -> str | None:
    """'switch to qwen', 'go back to gemini', 'use the local one'..., also 'switch to rose/clove'"""
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t or len(t.split()) > 12:
        return None
    for name, pat in BRAIN_NAMES.items():
        if name in ("clove", "rose"):
            tail = r"(?: voice| one| now| instead| please| sir)*$"
            if re.search(rf"\b{SWITCH_VERB} (?:the |your )?(?:voice )?{pat}{tail}", t):
                return f"voice:{name}"
            continue
        tail = r"(?: brain| model| engine| one| mode| now| instead| please| sir)*$"
        if re.search(rf"\b{SWITCH_VERB} (?:the |your )?(?:brain |model |engine )?{pat}{tail}", t) or \
           re.search(rf"\b(?:use|activate|bring in|bring back|put on|talk to|let me talk to) (?:the |your )?{pat}{tail}", t):
            return name
    return None


class Assistant:
    def __init__(self, ui, speaker=None):
        self.ui, self.speaker = ui, speaker
        self.loop = asyncio.get_running_loop()
        self.client = None            # Gemini client: ask_gemini, screen vision and the Gemini brain use it
        if config.GEMINI_API_KEY:
            from google import genai
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.brains: dict = {}        # name -> brain, filled in by Clove
        self.active = ""              # name of the brain currently listening and speaking
        self.switching = ""           # name of the brain being warmed up for a switch
        # Restore saved voice preference (Clove/Rose) across restarts
        try:
            saved = VOICE_FILE.read_text().strip()
            if saved in ("clove", "rose"):
                config.VOICE = saved
                config.ACTIVE_VOICE = config.VOICE_MALE if saved == "clove" else config.VOICE_FEMALE
                config.ACTIVE_LOCAL_VOICE = config.LOCAL_VOICE_MALE if saved == "clove" else config.LOCAL_VOICE_FEMALE
        except OSError:
            pass
        self.run_task: asyncio.Task | None = None
        self.recent: collections.deque = collections.deque(maxlen=24)   # (role, text) carried over on a switch
        self.pending_notes: list[str] = []
        self._switch_asked = ""       # utterance already handled as a voice switch
        self.jobs = Jobs(self._job_changed, self._job_finished)
        self.day = DayMemory()        # today's plan and what is done/left, until the night log
        self.routines = Routines(self)
        self.tools = Toolbox(self)
        from call_agent import CallManager
        self.calls = CallManager(self)
        from wake import WakeGate
        self.wake = WakeGate(self)
        from dictate import Dictation
        self.dictation = Dictation(self)
        from focus import Focus
        self.focus = Focus(self)
        from pair import Pair
        self.pair = Pair(self)
        from dashboard import Dashboard
        self.dashboard = Dashboard(self)
        from notifications import Notifications
        self.messages = Notifications(self)      # message notifications: announced, and kept for "what came in?"
        from away import Away
        self.away = Away(self)                   # at the PC or not: messages go to Telegram while he's away
        from notch import Notch
        self.notch = Notch(self)             # Clove Notch app at the top of the screen, when it runs
        self._notch_utt = -1
        self.connected = False
        # audio / visual state
        self.muted = False
        self.half_duplex = False
        self.echo_tail = 0.4          # seconds the mic stays muted after Clove stops talking
        self.mic_level = 0.0
        self.noise_floor = 0.01       # adaptive room-noise estimate (RMS)
        self.mic_chunks = 0
        self.preroll = collections.deque(maxlen=10)   # ~320 ms kept so the first syllable isn't clipped
        self.gate_until = 0.0         # noise gate stays open until this time
        self.last_voice = 0.0
        self.last_audio = 0.0
        self.heard = False
        self.awaiting = False
        self.await_since = 0.0
        self.busy = 0
        self.mic = None               # audio.Mic, set by agent.py; re-pointed when headphones come and go
        self.route_label = ""
        self.pointer = None           # on-screen cursor (created on first use)
        self.last_narration = 0.0
        self.mute_output = False      # user pressed stop: drop audio until the turn ends
        # turn bookkeeping
        self.seq = 0
        self.cap_who = None
        self.user_utt = ""
        self._learn_utt = -1          # request whose first tool call was already offered to learned.py

    # ---- the active brain --------------------------------------------------------------
    @property
    def brain(self):
        return self.brains.get(self.active)

    def feed_audio(self, chunks: list[bytes], voice: bool, now: float):
        """Audio thread: gated mic audio (silence while the gate is closed) goes to the active brain."""
        if self.brain and self.connected:
            self.brain.feed_audio(chunks, voice, now)

    async def send_text(self, text: str):
        """A typed command or a button press, as the user's words."""
        if self.brain:
            await self.brain.send_text(text)

    async def notify(self, note: str):
        """A system note for the model (reminder due, job finished) - not a user request."""
        if self.brain and self.connected:
            await self.brain.notify(note)
        else:
            self.pending_notes.append(note)

    def job_note(self, job: Job) -> str:
        return (f"[Background job update - a system notification, not a request from {config.USER_NAME}] "
                f"{job.label[:100]} -> {job.id} {job.status}: {job.result[:job.deliver_chars]}\n"
                + (job.instruction or f"(Tell {config.USER_NAME} the outcome in {job.report}. Don't add "
                                      "details that aren't in this result.)"))

    async def deliver_job(self, job: Job):
        if self.brain and self.connected:
            await self.brain.deliver_job(job)
        else:
            self.pending_notes.append(self.job_note(job))

    def take_notes(self) -> list[str]:
        notes, self.pending_notes = self.pending_notes, []
        return notes

    def remember(self, role: str, text: str):
        """Conversation so far, handed to the other brain when you switch."""
        text = text.strip()
        if text and not (self.recent and self.recent[-1] == (role, text)):
            self.recent.append((role, text[:400]))
            if role == "assistant":
                self._notch_prompt()
                self.notch.reply(text)
            try:
                memory.add_turn(role, text)          # kept on disk, so it still knows after a restart
            except Exception:
                log.exception("memory: could not save the turn")

    # ---- switching brains ----------------------------------------------------------------
    def brain_status(self) -> dict:
        out = {}
        for k, b in self.brains.items():
            ok, why = b.available()
            out[k] = {"label": b.label, "ok": ok, "why": why}
        return out

    def send_engine(self):
        self.ui.send(type="engine", active=self.active, switching=self.switching, brains=self.brain_status())

    def initial_brain(self) -> str:
        want = config.BRAIN
        if want == "auto":
            try:
                want = STATE_FILE.read_text().strip()
            except OSError:
                want = "gemini"
        order = [want] + [k for k in self.brains if k != want]
        return next((k for k in order if k in self.brains and self.brains[k].available()[0]), "")

    def request_switch(self, name: str, source: str = "voice") -> str:
        """Start a switch in the background; returns what to tell the user."""
        if isinstance(name, str) and name.startswith("voice:"):
            v = name.split(":", 1)[1]
            import config
            if v not in ("clove", "rose"):
                return f"error: unknown voice '{v}' (known: clove, rose)"
            config.VOICE = v
            config.ACTIVE_VOICE = config.VOICE_MALE if v == "clove" else config.VOICE_FEMALE
            config.ACTIVE_LOCAL_VOICE = config.LOCAL_VOICE_MALE if v == "clove" else config.LOCAL_VOICE_FEMALE
            try:
                VOICE_FILE.write_text(v)
            except Exception:
                pass
            if getattr(self, "dashboard", None):
                self.ui.send(**self.dashboard.info())
            try:
                if hasattr(self, 'active_brain') and self.active_brain and hasattr(self.active_brain, 'reconnect'):
                    asyncio.create_task(self.active_brain.reconnect())
                elif self.active and self.brains.get(self.active) and hasattr(self.brains[self.active], 'reconnect'):
                    asyncio.create_task(self.brains[self.active].reconnect())
            except Exception:
                pass
            return f"Switching to {v.title()} voice, sir."
        name = {"local": "qwen", "cloud": "gemini", "free": "hybrid"}.get(name, name)
        brain = self.brains.get(name)
        if not brain:
            return f"error: unknown brain '{name}' (known: {', '.join(self.brains)})"
        if name == self.active and not self.switching:
            return f"{brain.label} is already the active brain; nothing to do."
        if self.switching == name:
            return f"Already switching to {brain.label}."
        ok, why = brain.available()
        if not ok:
            self.ui.send(type="notice", text=f"{brain.label} isn't available: {why}")
            return f"error: {brain.label} isn't available ({why})"
        asyncio.create_task(self._do_switch(name, source))
        return (f"Switching to {brain.label} now: it warms up while you keep talking, then takes over by itself. "
                "Say a few words that you are switching.")

    async def _wait_quiet(self, cap: float):
        """Let the current brain finish the sentence it is saying; never wait for it to *think* (a slow model
        could still be pondering the very command that asked for the switch)."""
        t0, quiet_since = time.monotonic(), None
        while time.monotonic() - t0 < cap:
            await asyncio.sleep(0.15)
            quiet_since = None if self.speaking() else (quiet_since or time.monotonic())
            if quiet_since and time.monotonic() - quiet_since > 0.4:
                return

    async def _do_switch(self, name: str, source: str):
        brain = self.brains[name]
        self.switching = name
        self.send_engine()
        t0 = time.monotonic()
        try:
            self.ui.send(type="notice", text=f"Warming up {brain.label}…")
            await brain.prepare()                         # the old brain keeps serving meanwhile
            if source == "voice":
                await self._wait_quiet(5)
            old, old_task = self.brain, self.run_task
            if old_task:
                old_task.cancel()
                await asyncio.gather(old_task, return_exceptions=True)
            if self.speaker:
                self.speaker.clear()
            self.mute_output = False
            self.awaiting = False
            brain.adopt(list(self.recent))
            self.active = name
            self.run_task = asyncio.create_task(brain.run())
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                STATE_FILE.write_text(name)
            except OSError:
                pass
            log.info("switched to %s in %.1fs", name, time.monotonic() - t0)
            if old:
                asyncio.create_task(old.release())        # e.g. free the GPU after a while
            asyncio.create_task(self._greet(brain))
        except Exception as e:
            log.exception("switch to %s failed", name)
            self.ui.send(type="notice", text=f"Couldn't switch to {brain.label}: {str(e)[:120]}")
        finally:
            self.switching = ""
            self.send_engine()
            self.ui.send(type="notice", text="")

    async def _greet(self, brain):
        for _ in range(100):                              # up to ~10 s for the new brain to be ready
            if self.connected and self.brain is brain:
                break
            await asyncio.sleep(0.1)
        else:
            return
        try:
            await brain.greet()
        except Exception as e:
            log.warning("greeting failed: %s", e)

    # ---- inputs from the window and the microphone -------------------------
    def on_ui(self, m: dict):
        t = m.get("type")
        if t == "mute":
            self.muted = bool(m.get("value"))
        elif t == "text":
            text = str(m.get("text", "")).strip()[:2000]
            if text:
                self.wake.wake("typed")
                self.user_said(text, typed=True)
                asyncio.create_task(self.send_text(text))
        elif t == "stop":
            self.stop_speaking()
        elif t == "approve":
            self.wake.wake("button")
            ok = bool(m.get("value"))
            self.caption("you", "Approved the plan." if ok else "Rejected the plan.", new=True)
            self.tools.set_approval(ok, "pressed the button")
            asyncio.create_task(self.send_text(
                "(I pressed Approve on the plan, go ahead.)" if ok else "(I pressed Cancel on the plan, don't do it.)"))
        elif t == "cancel_job":
            self.jobs.cancel(str(m.get("id", "")))
        elif t == "engine":
            self.request_switch(str(m.get("value", "")), "ui")
        else:
            self.dashboard.on_ui(m)

    def on_mic(self, data: bytes, rms: float):
        """Audio thread. While Clove talks (and echo is possible) the mic is muted so he doesn't hear and
        obey himself; otherwise a noise gate only lets real speech through."""
        now = time.monotonic()
        echo = self.half_duplex and self.speaker is not None and (
            self.speaker.playing or now - self.speaker.last_sound < self.echo_tail or self.calls.audible())
        if not echo:      # noise floor: falls fast, rises slowly, so speech doesn't drag it up
            f = self.noise_floor
            self.mic_chunks += 1
            rate = 0.2 if self.mic_chunks < 45 else (0.1 if rms < f else 0.002)   # calibrate in the first ~1.5 s
            self.noise_floor = f + rate * (rms - f)
        voice = rms > max(0.004, self.noise_floor * 2.5) and not echo and not self.muted
        self.mic_level = 0.0 if echo or self.muted else min(1.0, max(0.0, rms - self.noise_floor) * 10)
        if voice:
            self.last_voice, self.heard = now, True

        if self.dictation.on_audio(data, voice and not echo and not self.muted, now):
            return                                           # dictating: his words are typed, not sent to a brain
        if not self.connected or self.muted:
            return
        chunks = [data]
        if echo:
            chunks = [bytes(len(data))]      # keep the stream flowing, but silent
            self.preroll.clear()
        elif config.NOISE_GATE:
            if voice:
                if now >= self.gate_until:   # gate opening: send the audio just before the voice too
                    chunks = list(self.preroll) + chunks
                    self.preroll.clear()
                self.gate_until = now + 0.6
            if now >= self.gate_until:
                self.preroll.append(data)
                chunks = [bytes(len(data))]
        if self.wake.enabled:
            for frame in self.wake.take_replay():           # "Clove, open YouTube": the words that woke him
                self.feed_audio([frame], True, now)
            chunks = self.wake.filter(chunks, voice and not echo, now)
            if chunks is None:
                return
        self.feed_audio(chunks, voice, now)

    def stop_speaking(self):
        if self.speaker:
            self.speaker.clear()
        self.mute_output = True
        if self.pointer and self.pointer.ok:
            self.pointer.hide()

    # ---- UI helpers ----------------------------------------------------------------
    def caption(self, who: str, text: str, new: bool | None = None):
        new = self.cap_who != who if new is None else new
        self.cap_who = who
        self.ui.send(type="caption", who=who, text=text, new=new)

    def activity(self, aid: str, kind: str, label: str, state: str, detail: str = "", job: str = ""):
        self.ui.send(type="activity", id=aid, kind=kind, label=label, state=state, detail=detail, job=job)

    def user_said(self, text: str, typed: bool = False, new: bool | None = None) -> bool:
        """Show the user's words; returns True when this starts a new request."""
        fresh = (self.cap_who != "you" or typed) if new is None else new
        if fresh:
            self.tools.utterance += 1
            self.tools.calls.clear()
            self.user_utt = ""
            if self.brain:
                self.brain.on_new_request()
        self.user_utt += text
        self.caption("you", text, new=True if typed else (True if new else None))
        decision = self.tools.on_user_words(self.user_utt)
        if decision:
            log.info("plan %s by the user's words: %r", decision, self.user_utt)
        if SLEEP.search(self.user_utt) and self.wake.enabled:
            self.wake.sleep()
            import sounds
            sounds.play(self, "sleep")
            log.info("asleep (asked)")
        target = parse_switch(self.user_utt)               # "switch to qwen": handled in code, not left to a model
        if target and target != self._switch_asked and (target != self.active or self.switching):
            self._switch_asked = target
            log.info("voice command: switch to %s", target)
            self.request_switch(target, "voice")
        elif not target:
            self._switch_asked = ""
        return fresh

    # ---- tools -------------------------------------------------------------------------
    async def run_tool(self, name: str, a: dict, fc, gen: int = 0):
        """Run one tool call with activity rows, plan-step tracking and logging. Returns str or Job."""
        kind, label = describe(name, a)
        self.seq += 1
        aid = f"a{self.seq}"
        quiet = name in QUIET_TOOLS
        if not quiet:
            self.activity(aid, kind, label, "running")
            self._notch_prompt()
            self.notch.tool_start(LABELS_NOTCH.get(name, name), label)
        steps = self.tools.link_steps(name)
        log.info("→ %s %s", name, a)
        self.busy += 1
        try:
            out = await self.tools.execute(name, a, fc, gen, steps)
        except Exception as e:
            log.exception("tool %s crashed", name)
            out = f"error: {e}"
        finally:
            self.busy -= 1
        if isinstance(out, Job):
            out.activity_id, out.plan_steps = aid, steps
            self.activity(aid, out.kind, label, "running", out.progress or "starting…", job=out.id)
            return out
        out = str(out)
        if self.active == "gemini" and fc is not None and getattr(fc, "id", None) and self.user_utt:
            # Gemini Live answered his words with a tool: let the other brains learn it as an instant command
            if self._learn_utt != self.tools.utterance:
                self._learn_utt = self.tools.utterance
                import learned
                learned.store.observe(self.user_utt, name, a, not is_failure(out))
        log.info("← %s", out[:200].replace("\n", " | "))
        if not quiet:
            fail = is_failure(out)
            self.activity(aid, kind, label, "fail" if fail else "ok", out.splitlines()[0][:110] if fail else "")
            if not out.startswith("NEEDS APPROVAL"):
                self.notch.tool_end(LABELS_NOTCH.get(name, name), not fail)
            if steps:
                self.tools.finish_steps(steps, not fail)
        return out

    def _notch_prompt(self):
        """Clove Notch shows what he asked once per request, when CLOVE starts working on it."""
        if self.user_utt.strip() and self._notch_utt != self.tools.utterance:
            self._notch_utt = self.tools.utterance
            self.notch.prompt(self.user_utt.strip())

    # ---- seeing the screen, pointing -----------------------------------------------
    def _capture_clean(self):
        """Screenshot without Clove' own cursor in it (it would cover, or be mistaken for, the target)."""
        if self.pointer and self.pointer.ok:
            self.pointer.hide(now=True)
            time.sleep(0.2)
        return screen.capture()

    async def _chrome_shot(self):
        """A picture of the Chrome tab in front, through the extension (no desktop permission prompt). None if unavailable."""
        from browser_bridge import bridge
        if not bridge.connected:
            return None
        out = await bridge.call("screenshot", timeout=15)
        if not out.startswith("data:image"):
            return None
        import base64
        import io
        from PIL import Image
        return Image.open(io.BytesIO(base64.b64decode(out.split(",", 1)[1]))).convert("RGB")

    async def look_at_screen(self, question: str) -> str:
        if not self.client:
            return "error: screen understanding needs the Gemini engine"
        from browser_bridge import bridge
        try:
            if bridge.active.get("focused") and (img := await self._chrome_shot()) is not None:
                return await screen.describe(self.client, question, img)     # Chrome is in front: its tab is the screen
            img = await asyncio.to_thread(self._capture_clean)
            return await screen.describe(self.client, question, img)
        except Exception as e:
            err = str(e)[:150]
            img = await self._chrome_shot() if "denied" in err or "cancel" in err else None
            if img is not None:
                text = await screen.describe(self.client, question, img)
                return ("(The desktop screenshot permission is off, so this is only the Chrome tab in front.) " + text +
                        " [Tell sir once: to let me see the whole screen, allow screenshots for this app in GNOME Settings > Apps.]")
            if "denied" in err or "cancel" in err:
                return ("error: the desktop refused the screenshot (permission off or the prompt was cancelled). Tell sir: allow "
                        "screenshots for this app in GNOME Settings > Apps, or put Chrome in front and I can see the tab.")
            return f"error: couldn't look at the screen ({err})"

    async def point_at(self, target: str, hold: float = 8.0) -> str:
        if not self.client:
            return "error: pointing needs the Gemini engine"
        try:
            img = await asyncio.to_thread(self._capture_clean)
            hit = await screen.locate(self.client, target, img)
        except Exception as e:
            return f"error: couldn't look at the screen ({str(e)[:150]})"
        if not hit:
            return f"not found: I can't see '{target}' on the screen right now"
        if self.pointer is None:
            from pointer import Pointer
            self.pointer = await asyncio.to_thread(Pointer)
        if not self.pointer.ok:
            return f"error: the on-screen pointer isn't available ({self.pointer.error[:100]})"
        self.pointer.point(hit["x"], hit["y"], hit["label"], hit["box"], max(2.0, min(float(hold or 8), 30.0)))
        log.info("pointing at %r (%.0f, %.0f) via %s", hit["label"], hit["x"], hit["y"], hit["model"])
        return f"pointing at {hit['label']} (done; the cursor stays on screen for a few seconds)"

    def clear_pointer(self) -> str:
        if self.pointer and self.pointer.ok:
            self.pointer.hide()
        return "pointer hidden"

    # ---- narration of long jobs ------------------------------------------------------
    async def _narrator(self):
        """Long Claude jobs shouldn't be silent: say what is happening now, at most every ~16 s, and only when
        nobody is talking. If nothing new happens for a while, say it is still going."""
        MIN_GAP, FIRST_AFTER, HEARTBEAT, GLOBAL_GAP = 16.0, 6.0, 40.0, 8.0
        seen: dict[str, dict] = {}
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            quiet = (self.connected and not self.speaking() and not self.awaiting and not self.busy
                     and not self.focus.active and not self.dictation.on
                     and now - self.last_voice > 2.0 and now - self.last_narration > GLOBAL_GAP)
            for job in self.jobs.running():
                if job.kind not in ("claude", "chrome") or not job.task_id:
                    continue
                st = seen.setdefault(job.id, {"seq": 0, "t": now - (MIN_GAP - FIRST_AFTER), "said": ""})
                fresh = (job.progress_seq > st["seq"] and job.progress and job.progress != st["said"]
                         and not re.match(r"(here'?s|here is|done|all done|finished|that'?s)\b", job.progress, re.I))
                beat = not fresh and now - st["t"] >= HEARTBEAT and job.progress
                if not quiet or not (fresh and now - st["t"] >= MIN_GAP or beat):
                    continue
                what = job.label[:70]
                if fresh:
                    note = (f"[Progress narration - a system note, not a request] Tell {config.USER_NAME}, in the "
                            f"first person and at most 12 words, what you are doing right now: \"{job.progress}\". "
                            "Just say it. Do not call tools or ask anything.")
                else:
                    note = (f"[Progress narration - a system note, not a request] The long job \"{what}\" is still "
                            f"running; the latest step was \"{job.progress}\". In at most 12 words, tell "
                            f"{config.USER_NAME} you are still on it and what you are doing. Do not call tools.")
                st.update(seq=job.progress_seq, t=now, said=job.progress)
                self.last_narration = now
                log.info("narrating %s: %s", job.id, job.progress)
                await self.notify(note)
                break                                     # one job per tick

    # ---- reminders & jobs ------------------------------------------------------------
    def set_reminder(self, minutes: float, message: str) -> str:
        if not 0 < minutes <= 24 * 60:
            return "error: minutes must be between 0 and 1440"
        when = time.strftime("%H:%M", time.localtime(time.time() + minutes * 60))
        self.loop.call_later(minutes * 60, lambda: asyncio.create_task(self._remind(message)))
        return f"reminder set for {when}"

    async def _remind(self, message: str):
        import desktop
        await asyncio.to_thread(desktop.notify, "Reminder", message)
        await self.notify(f"[Reminder due - a system notification] Politely remind {config.USER_NAME} now: {message}")

    def _job_changed(self, job: Job):
        if job.step_marks and job.plan_steps:
            self.tools.mark_steps(job.step_marks, job.plan_steps)
        state = {"running": "running", "done": "ok"}.get(job.status, "fail")
        detail = job.progress if job.status == "running" else job.result.splitlines()[0][:110]
        self.activity(job.activity_id or job.id, job.kind, job.label, state, detail, job=job.id)

    def _job_finished(self, job: Job):
        import sounds
        self.wake.wake("job finished")
        if job.kind not in ("think",):
            sounds.play(self, "done" if job.status == "done" else "fail")
        if job.plan_steps:
            self.tools.finish_steps(job.plan_steps, job.status == "done")
        asyncio.create_task(self._finish_job(job))

    async def _finish_job(self, job: Job):
        try:                                           # keep the whole result: "what did you find?" works hours later
            kind = "research" if job.label.startswith("Research") else ("browser" if job.kind == "chrome" else "job")
            rid = await asyncio.to_thread(memory.save_job, kind, job.label, job.result, job.status)
            if job.status == "done":
                job.result = job.result + f"\n[stored in memory as #{rid}]"
        except Exception:
            log.exception("memory: could not save %s", job.id)
        try:
            await self.routines.on_finished(job)       # routine jobs: save tasks, close the day, show the report
        except Exception:
            log.exception("post-processing %s failed", job.id)
        if job.label.startswith("[OpenCode"):
            asyncio.create_task(self._idle_ollama())
        self.notch.job_done(job.label, job.status == "done", job.result)
        if job.meta.get("phone"):                      # started from his phone: text him the result as well
            import phone
            asyncio.create_task(asyncio.to_thread(phone.send, f"{job.label[:80]}: {job.status}\n{job.result[:1500]}"))
        if self.focus.hold(job):
            log.info("%s finished during focus mode; told at the end", job.id)
            return
        await self.deliver_job(job)

    def _screen_changed(self, note: str):
        self._screen_note, self._screen_at = note, time.monotonic()

    async def _screen_feeder(self):
        """Tell the Gemini brain what he is looking at as it changes, silently (no reply), while nobody is talking,
        so "open Sam's chat" needs no extra look first. The Qwen brain gets it with each request instead."""
        import deskctx
        self._screen_note, self._screen_at, sent = "", 0.0, ""
        desk, desk_at = "", 0.0
        while True:
            await asyncio.sleep(0.4)
            if time.monotonic() - desk_at > 2:                 # the focused window / folder / git branch
                desk_at = time.monotonic()
                d = await asyncio.to_thread(deskctx.note)
                if d != desk:
                    desk, self._screen_at = d, time.monotonic()
            note = "; ".join(x for x in (self._screen_note, desk) if x)
            if (not note or note == sent or time.monotonic() - self._screen_at < 1.0 or self.active != "gemini"
                    or not self.wake.awake()                     # asleep: nothing goes to the cloud
                    or not self.connected or self.speaking() or self.awaiting or getattr(self, "heard", False)):
                continue
            ctx = getattr(self.brain, "context", None)
            if not ctx:
                continue
            try:
                await ctx(f"[Screen update, no reply needed] He is now looking at: {note}")
                sent = note
            except Exception as e:
                log.debug("screen note not sent: %s", e)

    async def _memory_keeper(self):
        """Background housekeeping: tidy once a day, and every half hour let Gemini pull lasting facts and to-dos out of
        the new conversation. Failures never reach the user."""
        await asyncio.sleep(45)
        while True:
            try:
                await asyncio.to_thread(memory.tidy)
                if self.client:
                    await asyncio.to_thread(memory.embed_pending, self.client)
                    r = await memory.learn(self.client, config.BRAIN_MODELS)
                    if r.startswith("learned") and not r.startswith("learned 0 facts and 0"):
                        log.info("memory: %s", r)
            except Exception as e:
                log.warning("memory housekeeping: %s", str(e)[:120])
            await asyncio.sleep(1800)

    async def _idle_ollama(self):
        """An OpenCode job ended: if nothing else uses Qwen, unload it and stop the server after a short grace period."""
        await asyncio.sleep(90)
        if self.active == "qwen" or any(j.label.startswith("[OpenCode") for j in self.jobs.running()):
            return
        import ollama_ctl
        await asyncio.to_thread(ollama_ctl.release)

    async def _phone(self):
        from phone import PhoneInbox
        try:
            await PhoneInbox(self).run()
        except Exception as e:
            log.warning("phone inbox stopped: %s", e)

    async def _ctl(self):
        import ctl
        try:
            await ctl.serve(self)
        except Exception as e:
            log.warning("control socket unavailable: %s", e)

    # ---- main loop & visual state ----------------------------------------------------
    async def run(self, stop: asyncio.Event):
        self._apply_route(await asyncio.to_thread(pick_route))
        first = self.initial_brain()
        log.info("brains: %s | starting with %s | echo guard %s (tail %.1fs)", ", ".join(self.brains), first or "none",
                 "on" if self.half_duplex else "off", self.echo_tail)
        from browser_bridge import bridge
        bridge.on_change = self._screen_changed
        bridge.on_stale = lambda have, want: (log.warning("Chrome extension is out of date (v%s, need v%s)", have, want),
                                              self.ui.send(type="notice", text=f"Reload the Clove Hands extension in Chrome (v{have} loaded, v{want} available): chrome://extensions"))
        await bridge.start()
        tasks = [asyncio.create_task(c) for c in (self._ticker(), self._watch_audio_route(), self._narrator(), self._memory_keeper(), self._screen_feeder(), self._ctl(), self._phone(), self.messages.run(), self.away.run(),
                                                     self.dashboard.run())]
        self.send_engine()
        if not first:
            self.ui.send(type="notice", text="No brain available: add GEMINI_API_KEY or install the local model.")
        else:
            try:
                self.ui.send(type="notice", text=f"Starting {self.brains[first].label}…")
                await self.brains[first].prepare()
            except Exception as e:                       # e.g. the local model failed to load: fall back
                log.exception("could not start %s", first)
                other = next((k for k in self.brains if k != first and self.brains[k].available()[0]), "")
                self.ui.send(type="notice", text=f"{self.brains[first].label} failed to start ({str(e)[:80]})"
                                                 + (f"; using {self.brains[other].label}" if other else ""))
                first = other
            if first:
                self.active = first
                self.run_task = asyncio.create_task(self.brains[first].run())
                self.ui.send(type="notice", text="")
        self.send_engine()
        try:
            await stop.wait()
        finally:
            for t in tasks + ([self.run_task] if self.run_task else []):
                t.cancel()

    def _apply_route(self, route):
        self.half_duplex = self._want_half_duplex(route.echo_possible)
        self.echo_tail = route.tail
        if route.label != self.route_label:
            self.route_label = route.label
            log.info("audio: %s | echo guard %s", route.label, "on" if self.half_duplex else "off")
            self.ui.send(type="route", label=route.label, headset=route.headset)

    def _want_half_duplex(self, echo_possible: bool) -> bool:
        return self.speaker is not None and (
            config.ECHO_GUARD == "on" or (config.ECHO_GUARD == "auto" and echo_possible))

    async def _watch_audio_route(self):
        """Follow the system's audio devices: when headphones connect or disconnect, the speaker moves by itself
        (PipeWire), and the microphone is re-pointed here without restarting Clove."""
        while True:
            await asyncio.sleep(3)
            route = await asyncio.to_thread(pick_route)
            if self.mic and self.mic.device is None and route.source != self.mic.source:
                log.info("microphone %s -> %s", self.mic.source, route.source)
                try:
                    await asyncio.to_thread(self.mic.reopen, route.source)
                    self.noise_floor, self.mic_chunks = 0.01, 0          # recalibrate to the new mic
                except Exception as e:
                    log.warning("could not switch microphone: %s", e)
            self._apply_route(route)

    def speaking(self) -> bool:
        return self.speaker.playing if self.speaker else time.monotonic() - self.last_audio < 0.4

    def compute_state(self) -> str:
        now = time.monotonic()
        if not self.connected:
            return "working" if self.switching else "offline"
        if self.dictation.on:
            return "dictating"
        if self.speaking():
            return "speaking"
        if not self.muted and now - self.last_voice < 0.6:
            return "listening"
        if self.awaiting:
            return "thinking"
        if self.busy or self.jobs.running():
            return "working"
        if self.tools.plan and self.tools.plan.get("approval") == "pending":
            return "waiting"
        if self.focus.active and not self.wake.awake(now):
            return "focus"
        if not self.wake.awake(now):
            return "sleeping"
        return "idle"

    async def _ticker(self):
        """~20 Hz: derive the visual state and push it to the window."""
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            if self.heard and now - self.last_voice > 0.7 and not self.awaiting and not self.speaking():
                self.heard, self.awaiting, self.await_since = False, True, now
            if self.awaiting and now - self.await_since > 30:
                self.awaiting = False
            self.ui.send(type="tick", state=self.compute_state(), mic=round(self.mic_level, 3),
                         out=round(self.speaker.level if self.speaker else 0.0, 3), tasks=len(self.jobs.running()))

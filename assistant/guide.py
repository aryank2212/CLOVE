"""Guided tours: "show me how to export a PDF in GIMP". Clove looks at the screen, says the next step, points at it
with the glowing cursor, waits until the screen changes (he did it), and goes on until the goal is reached.
Uses the cheap vision model; at most MAX_STEPS steps; "stop the tour" (cancel_job) ends it."""
import asyncio
import hashlib
import json
import logging
import re

import screen

log = logging.getLogger("clove.guide")
MAX_STEPS = 14
WAIT_S = 90                     # per step, for him to act
ASK = ("You are guiding a user step by step to reach this goal on their computer: {goal}\n"
       "Steps already given: {done}\n"
       "Look at the screenshot and reply with ONLY a JSON object: "
       '{{"done": true|false, "say": "<the next instruction, one short spoken sentence>", '
       '"target": "<the exact on-screen element to click or type into, as it appears, or empty>"}}. '
       "done=true (with a short congratulation in say) when the goal is already visible as achieved.")


def _fingerprint(img) -> str:
    small = img.convert("L").resize((64, 36))
    return hashlib.md5(small.tobytes()).hexdigest()


async def tour(a, goal: str, progress) -> str:
    done: list[str] = []
    for step in range(1, MAX_STEPS + 1):
        img = await asyncio.to_thread(a._capture_clean)
        reply = await screen.describe(a.client, ASK.format(goal=goal, done="; ".join(done) or "none"), img)
        m = re.search(r"\{.*\}", reply, re.S)
        try:
            plan = json.loads(m.group(0)) if m else {}
        except ValueError:
            plan = {}
        say, target = str(plan.get("say", "")).strip(), str(plan.get("target", "")).strip()
        if plan.get("done"):
            return f"Tour finished after {step - 1} steps. {say}"
        if not say:
            return f"I lost track of the screen after {step - 1} steps; ask me to look again."
        progress(f"step {step}: {say}")
        a.wake.wake("guide")
        await a.notify(f"[Guided tour - a system note] Say exactly this to him, nothing else, no tools: {say}")
        if target:
            await a.point_at(target, hold=12)
        done.append(say)
        before = _fingerprint(img)
        for _ in range(int(WAIT_S / 1.5)):                 # wait for him to do it
            await asyncio.sleep(1.5)
            now = await asyncio.to_thread(a._capture_clean)
            if _fingerprint(now) != before:
                await asyncio.sleep(1.2)                   # let the new screen settle
                break
        else:
            return f"Stopped the tour at step {step}: the screen didn't change for {WAIT_S} seconds."
    return f"Stopped after {MAX_STEPS} steps; the goal may need a different route."

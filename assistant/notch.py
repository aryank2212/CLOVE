"""CLOVE on Clove Notch (notch/ in this repository): Clove reports its own work there the way a
coding agent does, as its own "CLOVE" pill. What he asked, each tool as it runs, the reply, finished jobs, and a
plan waiting for approval, with Allow / Deny on Clove Notch that approve or reject it here.

Clove Notch listens on $XDG_RUNTIME_DIR/clove-notch.sock (one JSON line per event, the hook format of its
pipe.rs). A PermissionRequest keeps the connection open until someone clicks: Clove Notch writes back `allow` or
`deny`. If Clove Notch isn't running every call is a no-op, so Clove never waits on it.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("clove.notch")
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "clove-notch.sock"
SESSION = "clove"
DECISION_WAIT_S = 105                # Clove Notch answers within its own 108 s


class Notch:
    def __init__(self, a):
        self.a = a
        self.pending: asyncio.Task | None = None      # the approval card on Clove Notch, if any
        self.started = False
        self.queue: asyncio.Queue | None = None       # events go out one at a time, in the order they happened
        self.worker: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        return SOCK.exists()

    def _payload(self, event: str, **fields) -> dict:
        cwd = ""
        try:
            w = getattr(self.a, "dashboard", None)
            cwd = (w.last_ws if w else "") or str(Path.home())
        except Exception:
            cwd = str(Path.home())
        return {"hook_event_name": event, "session_id": SESSION, "cwd": cwd, "clove_agent": "clove", **fields}

    async def _write(self, payload: dict):
        """Connect and send one event line; returns the open connection, or None if Clove Notch isn't there."""
        try:
            r, w = await asyncio.wait_for(asyncio.open_unix_connection(str(SOCK)), 0.5)
            w.write((json.dumps(payload) + "\n").encode())
            await w.drain()
            return r, w
        except (OSError, asyncio.TimeoutError, ConnectionError):
            return None

    async def _drain(self):
        while True:
            payload, answer = await self.queue.get()
            conn = await self._write(payload)
            if answer is None:                            # fire and forget
                if conn:
                    conn[1].close()
            elif not conn:
                answer.set_result("")
            else:                                         # a card: its answer is awaited without holding up the queue
                asyncio.ensure_future(self._read_answer(conn, answer))

    @staticmethod
    async def _read_answer(conn, answer: asyncio.Future):
        r, w = conn
        try:
            line = await asyncio.wait_for(r.readline(), DECISION_WAIT_S)
            if not answer.done():
                answer.set_result(line.decode(errors="replace").strip())
        except (OSError, asyncio.TimeoutError, ConnectionError):
            if not answer.done():
                answer.set_result("")
        finally:
            w.close()

    def _enqueue(self, payload: dict, answer: asyncio.Future | None = None):
        if self.queue is None:
            self.queue = asyncio.Queue()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.ensure_future(self._drain())
        if not self.started:
            self.started = True
            if payload["hook_event_name"] != "SessionStart":
                self.queue.put_nowait((self._payload("SessionStart"), None))
        self.queue.put_nowait((payload, answer))

    async def _send(self, payload: dict, wait: bool = False) -> str:
        if not wait:
            self._enqueue(payload)
            return ""
        answer = asyncio.get_running_loop().create_future()
        self._enqueue(payload, answer)
        return await answer

    def event(self, event: str, **fields):
        """Fire and forget, in order (call it from the event loop)."""
        if self.available:
            self._enqueue(self._payload(event, **fields))

    # ---- what Clove reports ------------------------------------------------------------------------
    def prompt(self, text: str):
        self.event("UserPromptSubmit", prompt=text[:300])

    def tool_start(self, label: str, detail: str = ""):
        self.event("PreToolUse", tool_name=label[:60], tool_input={"command": detail[:120]} if detail else {})

    def tool_end(self, label: str, ok: bool):
        self.event("PostToolUse" if ok else "PostToolUseFailure", tool_name=label[:60], tool_input={})

    def reply(self, text: str):
        self.event("Stop", last_assistant_message=text[:400])

    def job_done(self, label: str, ok: bool, result: str):
        if ok:
            self.event("Stop", last_assistant_message=f"{label[:80]}: {result.splitlines()[0][:200] if result else 'done'}")
        else:
            self.event("StopFailure", message=f"{label[:80]} failed")

    # ---- approvals ---------------------------------------------------------------------------------
    def ask_approval(self, plan: dict):
        """A plan needs his yes: put an Allow / Deny card on Clove Notch. Whichever answer comes first wins, the
        notch's or his voice/window; the other is dropped."""
        if not self.available:
            return
        if self.pending and not self.pending.done():
            self.pending.cancel()
        steps = "; ".join(s["text"] for s in plan.get("steps", []))[:300]
        target = f"{plan.get('title', 'Plan')}: {steps}" if steps else plan.get("title", "Plan")
        self.pending = asyncio.ensure_future(self._approve(target))

    async def _approve(self, target: str):
        answer = await self._send(self._payload("PermissionRequest", tool_name="CLOVE plan",
                                                tool_input={"command": target}), wait=True)
        plan = self.a.tools.plan
        if answer not in ("allow", "deny") or not plan or plan.get("approval") != "pending":
            return                                        # declined, timed out, or already answered elsewhere
        ok = answer == "allow"
        log.info("plan %s on Clove Notch", "approved" if ok else "rejected")
        self.a.caption("you", "Approved the plan on Clove Notch." if ok else "Rejected the plan on Clove Notch.", new=True)
        self.a.tools.set_approval(ok, "on Clove Notch")
        await self.a.send_text("(I approved the plan on Clove Notch, go ahead.)" if ok
                               else "(I rejected the plan on Clove Notch, don't do it.)")

    def approval_settled(self):
        """He answered by voice or in the window: take the card off Clove Notch."""
        if self.pending and not self.pending.done():
            self.pending.cancel()
            self.event("Interrupt")

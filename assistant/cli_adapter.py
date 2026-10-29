"""Coding/ops agents Clove can hand complex work to: Claude Code, Codex, Gemini CLI, Kilo, OpenCode, Hermes Agent
and Crush, on this PC or on any machine in config.MACHINES (over SSH).

An agent is named `cli` or `cli@machine` ("gemini@anton"). With no agent named, config.AGENT_PRIORITY is tried in
order and the first one that is installed, logged in and has quota does the job, so Clove keeps working when
Claude Code isn't available. Every CLI runs headless: the task goes in on stdin (no quoting problems), the
final answer comes back on stdout and Clove speaks it.
"""
import asyncio
import os
import shlex
import signal
import time
from dataclasses import dataclass

import config
import machines

NOTE = ("You were started by Clove, {user}'s voice assistant, on the machine '{machine}'. Nobody is at this "
        "terminal: never wait for input, make reasonable choices yourself. If something needs root or a system change, "
        "do not attempt it: say exactly which command is needed and Clove will run it after asking. Do the task completely "
        "and verify it worked. End with a final message of at most 3 short plain sentences (no markdown) saying "
        "what you did and the outcome; it is read aloud.\n\nTASK:\n")

# name -> shell command; "$T" holds the task (read from stdin), {model}/{effort} come from config.
# Every agent runs in its own safe mode: it may read and edit files in the work folder, but anything its CLI treats
# as dangerous (root, system changes, deleting outside the project) is refused, not auto-approved. Clove itself
# does system changes with run_command/service, after the user's spoken yes.
CLIS = {
    "claude": 'claude -p --model {claude_model} --effort {claude_effort} --permission-mode acceptEdits "$T"',
    "codex": 'codex exec --skip-git-repo-check --full-auto "$T"',
    "gemini": 'gemini --approval-mode auto_edit -p "$T"',
    "kilo": 'kilo run {kilo_model} "$T"',
    "opencode": 'opencode run {opencode_model} "$T"',
    "hermes": 'hermes -z "$T"',
    "crush": 'crush run --quiet "$T"',
}
# Output that means "this agent can't work right now" -> try the next one instead of reporting it.
UNUSABLE = ("not logged in", "please run /login", "/login", "login required", "unauthorized", "invalid api key",
            "api key not", "authentication", "quota", "rate limit", "rate-limit", "usage limit", "credit balance",
            "insufficient", "resource_exhausted", "429", "no such file or directory: '", "command not found")
# Some CLIs exit 0 on these; only trusted in a short reply, so a real answer mentioning "quota" still counts.
HARD_FAIL = ("not logged in", "please run /login", "quota exceeded", "usage limit", "credit balance is too low",
             "resource_exhausted")
_probe: dict[str, tuple[float, bool]] = {}      # "cli@machine" -> (checked_at, installed)
_bad: dict[str, tuple[float, str]] = {}         # agents that just failed for auth/quota, skipped for a while
BAD_FOR_S = 30 * 60


@dataclass
class RunResult:
    cli: str
    ok: bool
    output: str
    error: str = ""
    duration: float = 0.0
    returncode: int = 0


def split(agent: str, machine: str | None = None) -> tuple[str, str]:
    cli, _, m = (agent or "").strip().lower().partition("@")
    return cli, machines.resolve(m or machine or "local")


def _command(cli: str, machine: str) -> str:
    local = machine == "local"
    km = getattr(config, "KILO_MODEL", "") if local else ""
    om = config.OPENCODE_MODEL if local else ""
    cmd = CLIS[cli].format(claude_model=shlex.quote(config.CLAUDE_MODEL_COMPLEX),
                           claude_effort=shlex.quote(config.CLAUDE_EFFORT),
                           kilo_model=f"-m {shlex.quote(km)}" if km else "",
                           opencode_model=f"-m {shlex.quote(om)}" if om else "")
    if local and cli == "claude":
        import delegate
        try:
            cmd = shlex.quote(delegate.claude_bin()) + cmd[len("claude"):]
        except RuntimeError:
            pass
    return cmd


def _installed(cli: str, machine: str) -> bool:
    key = f"{cli}@{machine}"
    hit = _probe.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    if machine == "local":
        import shutil
        ok = bool(shutil.which(cli)) or (cli == "claude" and _claude_local())
    else:
        out = machines.run(machine, f"command -v {cli} >/dev/null && echo yes", 15, stdin="")
        ok = "yes" in out
    _probe[key] = (time.time(), ok)
    return ok


def _claude_local() -> bool:
    import delegate
    try:
        return bool(delegate.claude_bin())
    except RuntimeError:
        return False


_claude_auth: tuple[float, bool] = (0.0, True)
claude_auth_state = "unknown"                  # yes | no | unknown (the check hung or failed)


def claude_ready() -> bool:
    """Is the local Claude Code logged in? Cached 10 min; if the check itself hangs, assume yes."""
    global _claude_auth, claude_auth_state
    if time.time() - _claude_auth[0] < 600:
        return _claude_auth[1]
    import json
    import subprocess
    ok, state = True, "unknown"
    try:
        import delegate
        p = subprocess.run([delegate.claude_bin(), "auth", "status"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL)
        try:
            ok = bool(json.loads(p.stdout).get("loggedIn"))
        except ValueError:
            ok = "not logged in" not in (p.stdout + p.stderr).lower()
        state = "yes" if ok else "no"
    except RuntimeError:
        ok, state = False, "no"                      # not installed
    except (OSError, subprocess.TimeoutExpired):
        pass
    _claude_auth, claude_auth_state = (time.time(), ok), state
    if not ok:
        _bad["claude@local"] = (time.time(), "not logged in")
    return ok


def available(machine: str = "local") -> dict[str, bool]:
    return {c: _installed(c, machine) for c in CLIS}


def installed_list() -> list[str]:
    out = []
    for m in machines.names():
        out += [c if m == "local" else f"{c}@{m}" for c in CLIS if _installed(c, m)]
    return out


def chain() -> list[str]:
    """AGENT_PRIORITY entries that are installed and not cooling off after an auth/quota failure."""
    now, out = time.time(), []
    for a in config.AGENT_PRIORITY:
        try:
            cli, m = split(a)
        except ValueError:
            continue
        key = f"{cli}@{m}"
        if cli in CLIS and _installed(cli, m) and not (key in _bad and now - _bad[key][0] < BAD_FOR_S):
            out.append(key)
    return out


def best_cli() -> str:
    c = chain()
    return c[0] if c else "hermes@anton"


def status() -> str:
    rows = []
    for m in machines.names():
        have = [c for c in CLIS if _installed(c, m)]
        rows.append(f"{m}: {', '.join(have) or 'none'}")
    now = time.time()
    bad = [f"{k} ({why})" for k, (t, why) in _bad.items() if now - t < BAD_FOR_S]
    return ("Installed agents - " + "; ".join(rows) + ". Order tried: " + (", ".join(chain()) or "none")
            + (". Skipped for now: " + ", ".join(bad) if bad else ""))


def _unusable(text: str) -> str:
    low = text.lower()[-3000:]
    return next((u for u in UNUSABLE if u in low), "")


async def _exec(cli: str, machine: str, task: str, workdir: str, timeout: int, on_proc=None) -> RunResult:
    started = time.time()
    wd = workdir or "~"
    wd_q = "~" if wd == "~" else shlex.quote(os.path.expanduser(wd) if machine == "local" else wd)
    script = f'T="$(cat)"; cd {wd_q} 2>/dev/null || cd ~; NO_COLOR=1 {_command(cli, machine)} 2>&1'
    argv = ["bash", "-c", script] if machine == "local" else machines.ssh_argv(machine, script)
    prompt = NOTE.format(user=config.USER_NAME, machine=machine) + task
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    if on_proc:
        on_proc(proc)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return RunResult(f"{cli}@{machine}", False, "", f"timed out after {timeout // 60} min", time.time() - started)
    except asyncio.CancelledError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise
    text = out.decode(errors="replace").strip()
    rc, dur = proc.returncode, time.time() - started
    name = f"{cli}@{machine}"
    if rc == 255 and machine != "local":
        return RunResult(name, False, "", f"can't reach {machine} over SSH", dur, rc)
    if rc != 0 or (len(text) < 400 and any(h in text.lower() for h in HARD_FAIL)):
        return RunResult(name, False, text[-1500:], (_unusable(text) or f"exit {rc}") + ": " + text[-300:], dur, rc)
    return RunResult(name, True, text or "(no output)", "", dur, 0)


async def run_task(task: str, cli: str | None = None, workdir: str = "", timeout: int = 0, retries: int = 0,
                   machine: str | None = None, on_try=None, on_proc=None) -> RunResult:
    """Run `task` on one agent (cli or cli@machine), or down the priority chain when cli is empty/'auto'.
    on_try(name) is called before each attempt (progress for the window)."""
    timeout = timeout or config.AGENT_TIMEOUT_MIN * 60
    if cli and cli.lower() not in ("auto", "best", "any"):
        try:
            name, m = split(cli, machine)
        except ValueError as e:
            return RunResult(cli, False, "", str(e))
        if name not in CLIS:
            return RunResult(cli, False, "", f"unknown agent {name}; known: {', '.join(CLIS)}")
        if not _installed(name, m):
            return RunResult(f"{name}@{m}", False, "", f"{name} isn't installed on {m}")
        candidates = [f"{name}@{m}"]
    else:
        candidates = chain()
        if machine:                       # prefer agents on the machine the work is about
            m = machines.resolve(machine)
            candidates = [c for c in candidates if c.endswith("@" + m)] + [c for c in candidates if not c.endswith("@" + m)]
        if not candidates:
            return RunResult("none", False, "", "no coding agent is installed and logged in (see AGENT_PRIORITY)")
    errors = []
    for cand in candidates:
        name, m = cand.split("@")
        for attempt in range(retries + 1):
            if on_try:
                on_try(cand)
            r = await _exec(name, m, task, workdir, timeout, on_proc)
            if r.ok:
                _bad.pop(cand, None)
                return r
            if _unusable(r.error):
                _bad[cand] = (time.time(), _unusable(r.error))
                break
            if "timed out" in r.error:
                break
        errors.append(f"{cand}: {r.error[:160]}")
        if len(candidates) == 1:
            return r
    return RunResult(candidates[-1], False, "", "every agent failed - " + " | ".join(errors))


async def run_parallel(task: str, clis: list[str] | None = None, timeout: int = 300) -> list[RunResult]:
    """The same task on several agents at once (council mode)."""
    targets = clis or chain()[:3] or ["hermes@anton"]
    return await asyncio.gather(*[run_task(task, c, timeout=timeout) for c in targets])

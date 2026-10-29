"""Voice-driven git/PR flow via cli_adapter + desktop git."""
import asyncio
import logging
from cli_adapter import run_task

log = logging.getLogger("clove.git_flow")

async def git_status(workdir: str = "") -> str:
    r = await run_task("run git status --short && git log --oneline -5", cli="claude", workdir=workdir, timeout=60)
    return r.output if r.ok else f"error: {r.error}"

async def commit_and_push(message: str, workdir: str = "") -> str:
    cmd = f"git add -A && git commit -m {message!r} && git push"
    r = await run_task(cmd, cli="claude", workdir=workdir, timeout=120)
    return r.output if r.ok else f"error: {r.error}"

async def open_pr(title: str, body: str = "", workdir: str = "") -> str:
    cmd = f"gh pr create --title {title!r} --body {body!r}"
    r = await run_task(cmd, cli="claude", workdir=workdir, timeout=120)
    return r.output if r.ok else f"error: {r.error}"

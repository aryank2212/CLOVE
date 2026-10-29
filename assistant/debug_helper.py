"""Debug helper: read on-screen error, search, propose + apply fix."""
import asyncio
import logging
from cli_adapter import run_task, best_cli

log = logging.getLogger("clove.debug_helper")

async def debug_screen(question: str = "read the error on screen") -> str:
    # caller passes look_at_screen result; here we just orchestrate via cli
    prompt = ("You are a debugging assistant. The user is looking at an error. "
              "Ask them to share the error text, then diagnose and propose a fix. "
              "Question context: " + question)
    r = await run_task(prompt, cli=best_cli(), timeout=120)
    return r.output if r.ok else f"error: {r.error}"

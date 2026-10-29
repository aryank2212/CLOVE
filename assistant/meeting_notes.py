"""Auto-meeting notes: summarize a call transcript into action items."""
import asyncio
import logging
from cli_adapter import run_task, best_cli

log = logging.getLogger("clove.meeting_notes")

async def summarize(transcript: str) -> str:
    prompt = ("Summarize this meeting transcript. Output: (1) 3-5 sentence summary, "
              "(2) bullet list of decisions, (3) bullet list of action items with owners. "
              "Transcript:\n" + transcript[:12000])
    r = await run_task(prompt, cli=best_cli(), timeout=180)
    return r.output if r.ok else f"error: {r.error}"

"""Package tracker: scrape courier sites."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.package_tracker")
async def track(tracking_number, carrier=""):
    prompt = f"Look up tracking number {tracking_number} ({carrier}). Give status and ETA. Spoken, 2-3 sentences."
    r = await run_task(prompt, cli=best_cli(), timeout=90)
    return r.output if r.ok else f"error: {r.error}"

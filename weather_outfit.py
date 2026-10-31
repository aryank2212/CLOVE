"""Weather-aware outfit suggestion."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.weather_outfit")
async def suggest(location=""):
    prompt = f"What's the weather in {location or 'here'} today and what should I wear? 3-4 sentences, practical."
    r = await run_task(prompt, cli=best_cli(), timeout=90)
    return r.output if r.ok else f"error: {r.error}"

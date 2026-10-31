"""Restaurant finder via web search."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.restaurant_finder")
async def find(cuisine="", location="", prefs=""):
    prompt = f"Find 3 good {cuisine} restaurants in {location}. {prefs}. Include name, rating, price, one-line why. Spoken style."
    r = await run_task(prompt, cli=best_cli(), timeout=90)
    return r.output if r.ok else f"error: {r.error}"

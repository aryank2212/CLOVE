"""Travel agent: flights/hotels/itinerary."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.travel_agent")
async def plan(destination, dates="", budget="", prefs=""):
    prompt = f"Plan a trip to {destination}. Dates: {dates}. Budget: {budget}. Prefs: {prefs}. Give flights, hotels, 3-day itinerary. Concise."
    r = await run_task(prompt, cli=best_cli(), timeout=180)
    return r.output if r.ok else f"error: {r.error}"

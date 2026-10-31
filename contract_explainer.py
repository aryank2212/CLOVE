"""Contract explainer: explain a clause in plain English."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.contract_explainer")
async def explain(clause):
    prompt = "Explain this contract clause in plain English (3-5 sentences). Flag risks.\n\n" + clause
    r = await run_task(prompt, cli=best_cli(), timeout=120)
    return r.output if r.ok else f"error: {r.error}"

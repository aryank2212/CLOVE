"""Council mode: spawn N CLIs to debate a question, synthesize a verdict."""
import asyncio
import logging
from cli_adapter import run_parallel, best_cli

log = logging.getLogger("clove.council")

async def debate(question: str, clis: list[str] | None = None) -> str:
    prompt = ("Give a concise position (3-5 sentences) with reasoning on: " + question)
    results = await run_parallel(prompt, clis=clis, timeout=120)
    parts = []
    for r in results:
        parts.append(f"[{r.cli}] {'OK' if r.ok else 'FAIL'}: {r.output[:400] if r.ok else r.error}")
    synthesis_prompt = ("You are the chair. Synthesize these positions into one verdict (5-8 sentences), "
                        "noting agreement and disagreement:\n\n" + "\n\n".join(parts))
    # synthesize with best available CLI
    from cli_adapter import run_task
    s = await run_task(synthesis_prompt, cli=best_cli(), timeout=120)
    verdict = s.output if s.ok else "(synthesis failed: " + s.error + ")"
    return "Council debate:\n" + "\n".join(parts) + "\n\nVerdict:\n" + verdict

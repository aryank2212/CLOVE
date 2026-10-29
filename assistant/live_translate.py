"""Live translation scaffold: translate text via local model or cloud."""
import asyncio
from cli_adapter import run_task, best_cli

async def translate(text: str, target_lang: str = "english") -> str:
    prompt = f"Translate to {target_lang}, output only the translation: {text}"
    r = await run_task(prompt, cli=best_cli(), timeout=60)
    return r.output if r.ok else f"error: {r.error}"

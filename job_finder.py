"""Job finder: search job boards, draft cover letter."""
import asyncio, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.job_finder")
async def search(role, location="", skills=""):
    prompt = f"Find 3 {role} jobs in {location}. Skills: {skills}. List title, company, link, one-line. Concise."
    r = await run_task(prompt, cli=best_cli(), timeout=120)
    return r.output if r.ok else f"error: {r.error}"
async def cover_letter(role, company, resume=""):
    prompt = f"Write a concise cover letter for {role} at {company}. Resume highlights: {resume}. 3 short paragraphs."
    r = await run_task(prompt, cli=best_cli(), timeout=120)
    return r.output if r.ok else f"error: {r.error}"

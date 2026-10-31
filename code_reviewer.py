"""Auto code review on git commit."""
import asyncio, subprocess, logging
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.code_reviewer")
async def review_diff(workdir=""):
    try:
        diff = subprocess.run(["git","diff","--cached"],capture_output=True,text=True,cwd=workdir or None,timeout=30).stdout
        if not diff.strip():
            diff = subprocess.run(["git","diff","HEAD~1"],capture_output=True,text=True,cwd=workdir or None,timeout=30).stdout
    except Exception as e:
        return f"error: {e}"
    if not diff.strip():
        return "no diff to review"
    prompt = "Review this git diff. List bugs, security issues, style problems, and suggestions. Be concise.\n\n" + diff[:12000]
    r = await run_task(prompt, cli=best_cli(), timeout=180)
    return r.output if r.ok else f"error: {r.error}"

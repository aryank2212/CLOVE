"""Document summarizer: read PDF/text, summarize."""
import asyncio, logging, subprocess
from cli_adapter import run_task, best_cli
log = logging.getLogger("clove.doc_summarizer")
async def summarize(path):
    try:
        if path.lower().endswith(".pdf"):
            out = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=60).stdout
        else:
            out = open(path).read()
    except Exception as e:
        return f"error reading file: {e}"
    if not out.strip():
        return "could not extract text"
    prompt = "Summarize this document in 5-8 sentences, then list 3 key takeaways.\n\n" + out[:15000]
    r = await run_task(prompt, cli=best_cli(), timeout=180)
    return r.output if r.ok else f"error: {r.error}"

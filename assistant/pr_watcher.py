"""PR watcher: monitor a GitHub PR, notify on review/merge, merge on voice."""
import asyncio
import logging
import subprocess
import time

log = logging.getLogger("clove.pr_watcher")

async def status(pr_url: str) -> str:
    try:
        out = subprocess.run(["gh", "pr", "view", pr_url, "--json", "state,reviewDecision,title"],
                             capture_output=True, text=True, timeout=20).stdout
        return out.strip() or "no data"
    except Exception as e:
        return f"error: {e}"

async def watch(pr_url: str, speak_fn, interval: int = 120):
    last = None
    while True:
        try:
            st = await status(pr_url)
            if st != last:
                await speak_fn("PR update: " + st[:300])
                last = st
            if "MERGED" in st.upper():
                break
        except Exception as e:
            log.warning("pr_watch error: %s", e)
        await asyncio.sleep(interval)

async def merge(pr_url: str) -> str:
    try:
        out = subprocess.run(["gh", "pr", "merge", pr_url, "--squash"], capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip() or "done"
    except Exception as e:
        return f"error: {e}"

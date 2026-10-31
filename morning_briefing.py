"""Morning briefing: calendar + todos + Anton health + news, spoken."""
import asyncio
import logging
from cli_adapter import run_task, best_cli

log = logging.getLogger("clove.morning_briefing")

async def gather() -> str:
    parts = []
    # todos
    try:
        import memory
        todos = memory.todo_list("open", "today")
        parts.append("Todos: " + (todos if todos else "none open"))
    except Exception as e:
        parts.append(f"Todos: error {e}")
    # Anton health
    try:
        from anton_bridge import bridge
        parts.append("Anton: " + await bridge.health())
        ev = await bridge.recent_events(3)
        parts.append("Recent Anton events: " + ev.split("\n", 1)[-1][:300])
    except Exception as e:
        parts.append(f"Anton: error {e}")
    # news (via duckduckgo search)
    try:
        r = await run_task("Give 3 one-line tech news headlines for today.", cli=best_cli(), timeout=60)
        parts.append("News: " + (r.output if r.ok else "unavailable"))
    except Exception as e:
        parts.append(f"News: error {e}")
    # calendar (best effort via gcalcli if installed)
    try:
        import subprocess
        out = subprocess.run(["gcalcli", "agenda", "today", "today"], capture_output=True, text=True, timeout=15).stdout.strip()
        parts.append("Calendar: " + (out or "no events"))
    except Exception:
        parts.append("Calendar: gcalcli not installed")
    briefing = "\n".join(parts)
    # synthesize
    r = await run_task("Turn this into a concise spoken morning briefing (8-12 sentences): \n" + briefing,
                       cli=best_cli(), timeout=120)
    return r.output if r.ok else briefing

"""Bridge to Anton's Forge execution layer (and Hermes) over Tailscale.

Anton exposes its capabilities through Forge (http://<host>:8092), which runs
tools under staged autonomy (Level 0 diagnose / Level 1 approve / Level 2 auto)
and publishes events to Hermes. This module is Clove's client: it lists the
tools Anton offers and runs one, surfacing the result as a string. Approval
for act tools is handled by Forge + Hermes (Telegram), not by Clove.
"""
import asyncio
import json
import logging
import urllib.request
import urllib.error
from typing import Any

import config

log = logging.getLogger("clove.anton_bridge")

HOST = config.ANTON_HOST
FORGE_PORT = int(getattr(config, "ANTON_FORGE_PORT", "8092"))
FORGE_TOKEN = config.ANTON_FORGE_TOKEN
HERMES_PORT = int(getattr(config, "ANTON_HERMES_PORT", "8002"))

FORGE_BASE = f"http://{HOST}:{FORGE_PORT}"
HERMES_BASE = f"http://{HOST}:{HERMES_PORT}"


def _req(url: str, method: str = "GET", data: Any = None, token: str = "") -> dict:
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        body = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
        req.data = body
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


class AntonBridge:
    def __init__(self):
        self._tools: list[dict] = []
        self._tools_loaded_at: float = 0.0

    async def health(self) -> str:
        r = await asyncio.to_thread(_req, f"{FORGE_BASE}/health")
        if r.get("error"):
            return f"error: {r['error']}"
        return f"Anton Forge ok (autonomy level {r.get('autonomy_level')}, {r.get('tools')} tools)"

    async def list_tools(self, refresh: bool = False) -> str:
        import time
        if not self._tools or refresh or time.time() - self._tools_loaded_at > 300:
            r = await asyncio.to_thread(_req, f"{FORGE_BASE}/v1/tools", "GET", None, FORGE_TOKEN)
            if r.get("error"):
                return f"error: {r['error']}"
            self._tools = r if isinstance(r, list) else r.get("tools", [])
            self._tools_loaded_at = time.time()
        if not self._tools:
            return "no tools advertised by Anton"
        lines = [f"- {t.get('name')}: {t.get('description', '')}" for t in self._tools]
        return "Anton tools:\n" + "\n".join(lines)

    async def run(self, tool: str, args: dict | None = None) -> str:
        args = args or {}
        r = await asyncio.to_thread(_req, f"{FORGE_BASE}/v1/run", "POST",
                                   {"tool": tool, "args": args}, FORGE_TOKEN)
        if r.get("error"):
            return f"error: {r['error']}"
        decision = r.get("decision", "?")
        ok = r.get("ok")
        output = r.get("output", "")
        err = r.get("error")
        approval_id = r.get("approval_id")
        parts = [f"decision={decision}, ok={ok}"]
        if approval_id:
            parts.append(f"approval_id={approval_id} (pending operator approval via Hermes)")
        if output:
            parts.append(str(output)[:3000])
        if err:
            parts.append(f"error: {err}")
        return " | ".join(parts)

    async def recent_events(self, limit: int = 20) -> str:
        # Hermes binds to Anton's localhost only, so reach it via Forge's
        # hermes_events tool instead of a direct HTTP call.
        raw = await self.run("hermes_events", {"limit": limit})
        import json as _j, re
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            data = _j.loads(m.group(0)) if m else {}
            items = data.get("items", [])
            if not items:
                return "no recent Anton events"
            lines = [f"- [{e.get('severity','?')}] {e.get('module','?')}: {e.get('title','')} — {e.get('message','')}" for e in items[:limit]]
            return "Recent Anton events:\n" + "\n".join(lines)
        except Exception:
            return raw


bridge = AntonBridge()


async def talk_to_anton(message: str, context: str = "") -> str:
    """Ask Hermes Agent on Anton (its own AI, free Nous models) and return its reply. Hermes runs there with
    Anton's tools, so it can answer about the homelab from the inside."""
    import cli_adapter
    prompt = (context + "\n\n" if context else "") + message
    r = await cli_adapter.run_task(prompt, "hermes", machine="anton", timeout=180, retries=0)
    return r.output if r.ok else f"error: {r.error}"


def text_me(message: str) -> str:
    """Send a text message to the user via Telegram (if configured)."""
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        try:
            import config
            token = token or getattr(config, "TELEGRAM_BOT_TOKEN", "")
            chat = chat or getattr(config, "TELEGRAM_CHAT_ID", "")
        except Exception:
            pass
    if not token or not chat:
        return ("error: Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env "
                "(create a bot via @BotFather, get your chat id via @userinfobot).")
    data = __import__("urllib.parse").parse.urlencode({"chat_id": chat, "text": message}).encode()
    req = __import__("urllib.request").request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with __import__("urllib.request").request.urlopen(req, timeout=15) as r:
            return "sent" if r.status == 200 else f"error: HTTP {r.status}"
    except Exception as e:
        return f"error: {e}"

#!/usr/bin/env python3
"""Clove as an MCP server: coding agents (Claude Code, Codex, Gemini CLI, Kilo, OpenCode, Hermes...) can talk to
you through Clove's voice while they work. Tools:

  ask_user(question)   Clove asks you out loud and returns your spoken answer (waits up to 10 minutes)
  tell_user(message)   Clove says a short update out loud
  user_context()       what you're looking at right now (focused window, folder, git branch)

It is a tiny stdio JSON-RPC server with no dependencies; it reaches the running Clove through its control socket.
Register it once per agent, for example:
  claude mcp add clove -- python3 /path/to/clove/clove_mcp.py
  codex mcp add clove -- python3 /path/to/clove/clove_mcp.py
  gemini mcp add clove python3 /path/to/clove/clove_mcp.py
"""
import json
import os
import socket
import sys
from pathlib import Path

SOCK = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "clove" / "ctl.sock"
TOOLS = [
    {"name": "ask_user", "description": "Ask the user a question out loud through Clove, their voice assistant, and "
     "get their spoken answer. Use for decisions you can't make yourself (which option, missing details, permission). "
     "Keep the question short and spoken-style. Waits up to 10 minutes.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "tell_user", "description": "Say a short progress update or result out loud to the user through Clove "
     "(one or two sentences). Doesn't wait for an answer.",
     "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}},
    {"name": "user_context", "description": "What the user is looking at right now: the focused window, and for a "
     "terminal its folder and git branch.", "inputSchema": {"type": "object", "properties": {}}},
]


def ctl(line: str, timeout: float) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCK))
        s.sendall((line.replace("\n", " ") + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        return data.decode(errors="replace").strip()
    except (OSError, socket.timeout) as e:
        return f"error: Clove isn't reachable ({e}); is it running?"
    finally:
        s.close()


def call(name: str, args: dict) -> str:
    if name == "ask_user":
        return ctl("agent_ask " + str(args.get("question", "")), 620)
    if name == "tell_user":
        return ctl("say " + str(args.get("message", "")), 10)
    if name == "user_context":
        return ctl("context", 10)
    return f"error: unknown tool {name}"


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method", "")
        if mid is None:                                   # a notification (e.g. notifications/initialized)
            continue
        if method == "initialize":
            result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "clove", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params", {})
            text = call(p.get("name", ""), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": text}], "isError": text.startswith("error")}
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)


if __name__ == "__main__":
    main()

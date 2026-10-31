"""Deletion guard: recognises destructive actions so the approval gate (tools.Toolbox.needs_approval) asks HIM
before they run. It used to "confirm" by letting the model call a tool three times, which never asked a person and
also flagged harmless commands ("docker ps --format" contains the letters "rm"); now it only classifies, by whole
words, and the real yes/no comes from his voice or the Approve button.
"""
import json
import re
import time
import logging

log = logging.getLogger("clove.deletion_guard")

PENDING: dict[str, dict] = {}
EXPIRY = 60.0

DELETE_TOOL_NAMES = {
    "delete_file", "remove_file", "rm", "uninstall", "purge", "wipe", "erase",
    "destroy", "kill", "prune", "drop", "truncate",
}
DELETE_TOOL_SUBSTR = ("delete", "remove", "uninstall", "purge", "wipe", "erase",
                      "destroy", "prune", "drop", "truncate", "rm_")
DELETE_CMD_KEYWORDS = ("rm ", "rm -", "del ", "delete ", "drop ", "truncate ",
                       "uninstall", "purge", "shred ", "wipe", " rmdir", "unlink")
# A command word at the start of the line or after ; & | ( or sudo, never inside another word
_START = r"(?:^|[;&|(]\s*|\bsudo\s+)"
DELETE_CMD = re.compile(_START + r"(?:rm|rmdir|unlink|shred|truncate|wipefs|mkfs\S*)\b"
                        r"|\b(?:drop\s+(?:table|database|schema)|delete\s+from|truncate\s+table)\b"
                        r"|\b(?:uninstall|purge|autoremove)\b", re.I)
DOCKER_DESTRUCTIVE = re.compile(r"\b(?:docker|podman)(?:\s+compose|-compose)?\s+(?:\S+\s+)*?"
                                r"(?:rm|rmi|kill|prune|down|stop)\b", re.I)
GIT_DESTRUCTIVE = re.compile(r"\bgit\s+(?:reset\s+--hard|clean\s+-\w*f|branch\s+-D|push\s+(?:--force|-f)\b)", re.I)


def _key(name: str, a: dict) -> str:
    try:
        return name + "|" + json.dumps(a, sort_keys=True, default=str)
    except Exception:
        return name + "|" + str(a)


def is_deletion(name: str, a: dict) -> bool:
    nl = name.lower()
    if nl in DELETE_TOOL_NAMES:
        return True
    if any(s in nl for s in DELETE_TOOL_SUBSTR):
        return True
    # anton_run: check the underlying tool name
    if name == "anton_run":
        tool = str(a.get("tool", "")).lower()
        if any(s in tool for s in DELETE_TOOL_SUBSTR) or tool in DELETE_TOOL_NAMES:
            return True
    # run_command / sudo_command / run_in_terminal: inspect command
    if name in ("run_command", "sudo_command", "run_in_terminal"):
        cmd = str(a.get("command", ""))
        return bool(DELETE_CMD.search(cmd) or DOCKER_DESTRUCTIVE.search(cmd) or GIT_DESTRUCTIVE.search(cmd))
    # macro replay could contain deletions but skip (too complex)
    return False


def _describe(name: str, a: dict) -> str:
    if name in ("run_command", "sudo_command", "run_in_terminal"):
        return f"command: {a.get('command', '')}"
    if name == "anton_run":
        return f"Anton tool '{a.get('tool')}' args={a.get('args')}"
    return f"{name} {a}"


def check(name: str, a: dict) -> tuple[bool, str]:
    """Return (allowed, message). If not a deletion, (True, '')."""
    if not is_deletion(name, a):
        return True, ""
    key = _key(name, a)
    now = time.time()
    # expire
    entry = PENDING.get(key)
    if entry and now - entry["ts"] > EXPIRY:
        del PENDING[key]
        entry = None
    desc = _describe(name, a)
    if entry is None:
        PENDING[key] = {"ts": now, "stage": 1}
        return False, ("DELETE GUARD (1/2): This will DELETE: " + desc +
                       "\nNo action taken. To proceed, call this again (confirm 1/2). "
                       "Say 'cancel' to abort.")
    if entry.get("stage", 0) == 1:
        entry["stage"] = 2
        entry["ts"] = now
        return False, ("DELETE GUARD (2/2): FINAL confirmation. This will DELETE: " + desc +
                       "\nCall once more to execute. Say 'cancel' to abort.")
    # stage 2 done -> allow
    del PENDING[key]
    return True, "Confirmed (2/2). Executing deletion."


def cancel_all() -> str:
    n = len(PENDING)
    PENDING.clear()
    return f"cancelled {n} pending deletion(s)"

"""Semantic search across files + memory + notes."""
import subprocess
import logging
from pathlib import Path

log = logging.getLogger("clove.semantic_search")

def search_files(query: str, root: str = "~") -> str:
    try:
        out = subprocess.run(["grep", "-rl", query, root], capture_output=True, text=True, timeout=30).stdout
        return out.strip() or "no matches"
    except Exception as e:
        return f"error: {e}"

def search_memory(query: str) -> str:
    try:
        import memory
        return memory.recall(query) or "nothing in memory"
    except Exception as e:
        return f"error: {e}"

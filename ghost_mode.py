"""Ghost mode: local-only, no cloud, no logs, no memory writes. Toggle via voice."""
import json
from pathlib import Path
import config

_FLAG = Path(config.DATA_DIR) / "ghost_mode"

def is_on() -> bool:
    try:
        return _FLAG.read_text().strip() == "1"
    except FileNotFoundError:
        return False

def set_on(on: bool) -> str:
    _FLAG.parent.mkdir(parents=True, exist_ok=True)
    _FLAG.write_text("1" if on else "0")
    return "Ghost mode ON: local-only, no cloud, no logs, no memory writes." if on else "Ghost mode OFF: normal operation resumed."

def guard_memory_write() -> bool:
    """Return True if a memory write should be blocked."""
    return is_on()

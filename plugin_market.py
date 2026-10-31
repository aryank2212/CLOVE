"""Plugin marketplace scaffold: installable tools via voice."""
import json
from pathlib import Path
import config

_DIR = Path(config.DATA_DIR) / "plugins"
def list_plugins() -> str:
    if not _DIR.exists():
        return "no plugins installed"
    return ", ".join(p.stem for p in _DIR.glob("*.py")) or "no plugins installed"

def install(name: str, url: str) -> str:
    _DIR.mkdir(parents=True, exist_ok=True)
    return f"scaffold: would download {url} as {name}.py (not implemented)"

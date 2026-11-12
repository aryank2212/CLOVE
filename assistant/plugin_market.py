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
    # Downloading Python from a URL and running it would hand the computer to whoever controls that URL.
    return (f"Installing plugins from the internet is not supported, so nothing was downloaded from {url}. "
            f"To add one, review the file yourself and put it in {_DIR} as {name or 'name'}.py.")

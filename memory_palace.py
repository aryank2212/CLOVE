"""Memory palace: spatial memory."""
import json, time
from pathlib import Path
import config
import logging
log = logging.getLogger("clove.memory_palace")
_DIR = Path(config.DATA_DIR)/"palace"
def remember(location, item):
    _DIR.mkdir(parents=True,exist_ok=True)
    p=_DIR/(location+".json")
    data=json.loads(p.read_text()) if p.exists() else {"location":location,"items":[]}
    data["items"].append({"ts":time.time(),"item":item})
    p.write_text(json.dumps(data,indent=2))
    return f"Remembered '{item}' at {location}."
def recall(location):
    p=_DIR/(location+".json")
    if not p.exists(): return f"nothing at {location}"
    data=json.loads(p.read_text())
    return "\n".join(i["item"] for i in data["items"]) or f"nothing at {location}"
def list_locations():
    if not _DIR.exists(): return "no locations"
    return ", ".join(p.stem for p in _DIR.glob("*.json"))

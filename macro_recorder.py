"""Macro recording: record a sequence of tool calls, replay later."""
import json
from pathlib import Path
import config

_DIR = Path(config.DATA_DIR) / "macros"

def _path(name: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / (name + ".json")

class MacroRecorder:
    def __init__(self):
        self.recording: str | None = None
        self.steps: list[dict] = []

    def start(self, name: str) -> str:
        self.recording = name
        self.steps = []
        return f"Recording macro '{name}'. Do the steps; say 'stop recording' when done."

    def record(self, tool: str, args: dict):
        if self.recording:
            self.steps.append({"tool": tool, "args": args})

    def stop(self) -> str:
        if not self.recording:
            return "Not recording."
        _path(self.recording).write_text(json.dumps(self.steps, indent=2))
        n = len(self.steps)
        name = self.recording
        self.recording = None
        self.steps = []
        return f"Saved macro '{name}' with {n} steps."

    def list_macros(self) -> str:
        if not _DIR.exists():
            return "no macros saved"
        names = [p.stem for p in _DIR.glob("*.json")]
        return "Macros: " + ", ".join(names) if names else "no macros saved"

    async def replay(self, name: str, executor) -> str:
        p = _path(name)
        if not p.exists():
            return f"error: macro '{name}' not found"
        steps = json.loads(p.read_text())
        results = []
        for s in steps:
            try:
                r = await executor(s["tool"], s["args"])
                results.append(f"{s['tool']}: {str(r)[:120]}")
            except Exception as e:
                results.append(f"{s['tool']}: error {e}")
        return "Replayed " + name + ":\n" + "\n".join(results)

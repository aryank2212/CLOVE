"""Voice memo: record audio + transcription into memory."""
import asyncio
import logging
import subprocess
import time
from pathlib import Path
import config

log = logging.getLogger("clove.voice_memo")
MEMO_DIR = Path(config.DATA_DIR) / "memos"

def record(seconds: int = 30) -> str:
    MEMO_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = MEMO_DIR / f"memo_{ts}.wav"
    try:
        subprocess.run(["parec", "-d", "@DEFAULT_SOURCE@", "--file-format=wav", str(path)],
                       timeout=seconds + 2, capture_output=True)
    except subprocess.TimeoutExpired:
        pass
    return str(path)

async def transcribe_and_save(path: str, whisper_fn) -> str:
    text = await whisper_fn(path)
    try:
        import memory
        memory.remember(text, "memo")
    except Exception:
        pass
    return text

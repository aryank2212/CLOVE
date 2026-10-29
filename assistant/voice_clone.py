"""Voice cloning scaffold (XTTS)."""
def available() -> bool:
    try:
        import TTS  # noqa
        return True
    except Exception:
        return False

def clone(reference_audio: str, text: str) -> str:
    if not available():
        return "error: TTS (Coqui) not installed"
    return "scaffold: not implemented"

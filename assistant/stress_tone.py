"""Stress-aware tone scaffold: analyze voice features, adjust verbosity."""
def analyze(audio_path: str) -> dict:
    return {"stress": 0.0, "fatigue": 0.0, "note": "scaffold: needs audio feature extraction"}

def adjust(text: str, stress: float, fatigue: float) -> str:
    if stress > 0.7 or fatigue > 0.7:
        return "Keep it short: " + text
    return text

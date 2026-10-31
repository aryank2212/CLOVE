"""Face memory scaffold: on-device recognition (requires opencv + face_recognition)."""
def available() -> bool:
    try:
        import cv2, face_recognition  # noqa
        return True
    except Exception:
        return False

def remember(name: str, image_path: str) -> str:
    if not available():
        return "error: face_recognition not installed (pip install face_recognition opencv-python)"
    return "scaffold: not implemented"

def who_is(image_path: str) -> str:
    if not available():
        return "error: face_recognition not installed"
    return "scaffold: not implemented"

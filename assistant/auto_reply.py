"""Auto-reply drafts scaffold."""
def draft_reply(context: str, message: str) -> str:
    return "scaffold: would draft a reply to: " + message[:80]

def send_reply(platform: str, to: str, text: str) -> str:
    return f"scaffold: would send '{text[:60]}' to {to} on {platform}"

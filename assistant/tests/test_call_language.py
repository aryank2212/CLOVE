"""Hindi on calls: the agent's instructions, what the speech recogniser is told, and the default (English)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import call_agent  # noqa: E402
import turn_taking  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


def agent(prefs):
    a = SimpleNamespace(dashboard=SimpleNamespace(prefs=prefs))
    turn_taking.Recogniser.shared = classmethod(lambda cls: None)
    return call_agent.CallAgent(a, "take a message", "Priya", "phone", audio=None)


en, hi = agent({}), agent({"callhindi": True})
check("English by default", "Speak English by default" in en._prompt() and "Speak Hindi" not in en._prompt())
check("with the setting on, it speaks Hindi", "Speak Hindi" in hi._prompt() and "Speak English by default" not in hi._prompt())
check("the setting: Hindi", hi.hindi and not en.hindi)
check("the very first words are Hindi (no English greeting to copy)", 'Start by saying exactly "नमस्ते' in hi._prompt())
check("the instructions open and close with: speak only Hindi",
      hi._prompt().startswith("LANGUAGE: you speak ONLY Hindi") and hi._prompt().rstrip().endswith("they are for the owner)."))
check("English calls keep the English greeting", 'Start by saying exactly "Hello' in en._prompt() and "नमस्ते" not in en._prompt())
check("the recogniser is told the call is in Hindi", hi.turns.language == "hi" and en.turns.language is None)
heard = []


class FakeRec:
    model = object()

    def text(self, pcm, language=None):
        heard.append(language)
        return "ठीक है"


tt = turn_taking.TurnTaker(FakeRec(), "hi")
tt.in_turn, tt.turn_started = True, 1.0
tt._deciding = True
tt._decide(b"\0" * 32000, 1.0)
check("each pause is read as Hindi, not guessed", heard == ["hi"])
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

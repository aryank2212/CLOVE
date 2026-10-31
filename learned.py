"""Commands Clove learns by himself, so a model is needed less and less.

Every time a model answers a request with exactly one simple tool call, the pair is remembered. The words that
also appear in the call's arguments become a slot: "play lofi beats on youtube" -> play_youtube(query="lofi beats")
is stored as the pattern "play {query} on youtube". Once the same pattern has led to the same tool PROMOTE_AFTER
times with different slot values (or the identical sentence that many times), it becomes an instant command: the
next "play daft punk on youtube" runs play_youtube(query="daft punk") in code, in well under a second, for free.

Only harmless tools can be learned (nothing that deletes, installs, sends or spends). If a learned command fails,
the request goes to the model as usual; "forget that shortcut" removes the last one learned. Stored in ~/.local/share/clove/learned.json.
"""
import json
import logging
import re
import threading
import time

import config

log = logging.getLogger("clove.learned")
PATH = config.DATA_DIR / "learned.json"
PROMOTE_AFTER = 3
# Harmless actions whose result code can put into words (fastpath.direct_reply). Tools whose output needs a model to
# interpret (health reports, logs, lists) are left to the model.
LEARNABLE = {"open_bookmark", "open_url", "web_search", "open_app", "open_path", "volume", "media", "play_youtube",
             "play_spotify", "look_at_screen", "point_at", "clear_pointer", "dictate", "focus"}
# Leading/trailing words that don't change the meaning
FILLER = re.compile(r"^(?:(?:hey|ok(?:ay)?|so|um+|uh+|please|clove|rose|can you|could you|would you|will you|"
                    r"i want you to|i'?d like you to|just|now|go ahead and)\W+)+|(?:\W+(?:please|now|for me|thanks?|"
                    r"thank you|sir|clove|rose))+\W*$", re.I)
# Arguments that pick a mode ("set", "pause", "terminal"): part of the command itself, never a slot
ENUM_KEYS = {"action", "where", "status", "source", "platform", "direction", "mode", "complexity", "routine", "kind"}
_lock = threading.Lock()


def normalise(text: str) -> str:
    t = re.sub(r"\[system note.*", "", text, flags=re.I | re.S)
    t = re.sub(r"[^\w\s'%.-]+", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip(" .")
    prev = None
    while prev != t:
        prev, t = t, FILLER.sub("", t).strip(" .")
    return t


def _template(text: str, args: dict) -> tuple[str, dict, dict] | None:
    """Replace argument values that appear in the sentence with {slot}s. Returns (pattern, fixed args, slot types)."""
    pattern, fixed, types = text, {}, {}
    for k, v in sorted(args.items(), key=lambda kv: -len(str(kv[1]))):
        sv = (normalise(str(v)) if isinstance(v, (str, int, float)) and not isinstance(v, bool)
              and k not in ENUM_KEYS else "")
        if sv and (len(sv) >= 2 or not isinstance(v, str)) and f" {sv} " in f" {pattern} ":
            pattern = re.sub(rf"(?<!\S){re.escape(sv)}(?!\S)", "{" + k + "}", pattern, count=1)
            types[k] = type(v).__name__
        elif isinstance(v, (str, int, float, bool)):
            fixed[k] = v
        else:
            return None                                    # lists/objects: too complex to learn safely
    if len(pattern.split()) > 12 or pattern.strip("{} ") == "" or re.fullmatch(r"(\{\w+\}\s*)+", pattern):
        return None                                        # nothing literal left to recognise it by
    return pattern, fixed, types


def _regex(pattern: str) -> re.Pattern:
    out = re.escape(pattern)
    out = re.sub(r"\\\{(\w+)\\\}", lambda m: f"(?P<{m.group(1)}>.+?)", out)
    return re.compile(f"^{out}$")


def _cast(v: str, kind: str | None):
    try:
        return int(v) if kind == "int" else float(v) if kind == "float" else v
    except ValueError:
        return None


class Learned:
    def __init__(self):
        self.data: dict = {"patterns": {}}
        try:
            self.data = json.loads(PATH.read_text())
        except (OSError, ValueError):
            pass
        self._compiled: dict[str, re.Pattern] = {}

    def _save(self):
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1))
            tmp.replace(PATH)
        except OSError as e:
            log.warning("could not save learned commands: %s", e)

    def observe(self, text: str, tool: str, args: dict, ok: bool):
        """A model answered `text` with this single tool call."""
        if tool not in LEARNABLE:
            return
        norm = normalise(text)
        if not norm or len(norm) > 120:
            return
        tpl = _template(norm, args or {})
        if not tpl:
            return
        pattern, fixed, types = tpl
        key = f"{pattern}␟{tool}␟{json.dumps(fixed, sort_keys=True)}"
        with _lock:
            p = self.data["patterns"].setdefault(key, {"pattern": pattern, "tool": tool, "fixed": fixed,
                                                         "values": [], "count": 0, "promoted": False})
            p["types"] = types
            if ok:
                p["count"] += 1
                slots = {k: v for k, v in args.items() if k not in fixed}
                val = json.dumps(slots, sort_keys=True)
                if val not in p["values"]:
                    p["values"] = (p["values"] + [val])[-8:]
                p["last"] = time.time()
                varied = "{" in pattern and len(p["values"]) >= PROMOTE_AFTER
                same = "{" not in pattern and p["count"] >= PROMOTE_AFTER
                if not p["promoted"] and (varied or same):
                    p["promoted"] = True
                    log.info("learned a new instant command: %r -> %s", pattern, tool)
            self._save()

    def match(self, text: str) -> tuple[str, dict] | None:
        """(tool, args) when `text` matches a learned instant command."""
        norm = normalise(text)
        if not norm:
            return None
        best = None
        for key, p in self.data["patterns"].items():
            if not p.get("promoted"):
                continue
            rx = self._compiled.get(key) or self._compiled.setdefault(key, _regex(p["pattern"]))
            m = rx.match(norm)
            if m:
                # the most specific pattern (most literal text) wins
                lit = len(re.sub(r"\{\w+\}", "", p["pattern"]))
                slots = {k: _cast(v, p.get("types", {}).get(k)) for k, v in m.groupdict().items()}
                if None not in slots.values() and (not best or lit > best[0]):
                    best = (lit, p["tool"], {**p["fixed"], **slots})
        return (best[1], best[2]) if best else None

    def forget_last(self) -> str:
        with _lock:
            promoted = [(p.get("last", 0), k) for k, p in self.data["patterns"].items() if p.get("promoted")]
            if not promoted:
                return "There are no learned shortcuts yet."
            _, key = max(promoted)
            p = self.data["patterns"].pop(key)
            self._compiled.pop(key, None)
            self._save()
        return f"Forgotten the shortcut \"{p['pattern']}\"."

    def summary(self) -> str:
        rows = [f"\"{p['pattern']}\" -> {p['tool']}" for p in self.data["patterns"].values() if p.get("promoted")]
        return f"{len(rows)} learned shortcuts: " + "; ".join(rows[:20]) if rows else "No learned shortcuts yet."


store = Learned()

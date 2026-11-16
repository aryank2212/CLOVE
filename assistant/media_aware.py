"""Music and videos on the speakers: CLOVE knows they are playing, so it doesn't take the song for him.

The microphone hears the speakers. Without this, a song's lyrics reach the brain as if he were talking (and a line
with "Rose" in it can even wake CLOVE). While something else is playing:

  - Only a clear "Clove, ..." / "Hey Rose, ..." at the start of what he says wakes CLOVE (a name sung somewhere
    in a line doesn't), and a notification no longer wakes it by itself.
  - Once awake, it falls asleep again after MEDIA_WAKE_WINDOW_S seconds of quiet instead of the usual window.

It never changes the music's volume: an app's volume set by anyone is remembered by the desktop (WirePlumber) for
that app's next stream, so turning it down "for a moment" left Chrome nearly silent for good.

"Playing" means a media player says so (MPRIS: Spotify, a YouTube tab, mpv...) or another app's sound stream has
been running for a couple of seconds. CLOVE's own voice, Clove Notch's sounds and call audio don't count.
"""
import asyncio
import json
import logging
import os
import subprocess
import time

log = logging.getLogger("clove.media")
POLL_S = 1.5
MEDIA_WAKE_WINDOW_S = 10.0
OURS = ("clove-notch", "clove", "pipewire alsa [python")   # application names that are CLOVE's own sound


def _run(*args: str, timeout: float = 3) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def foreign_streams(raw: str | None = None) -> list[dict]:
    """Other apps' sound streams that are running now: [{index, app, volume}] (volume: per-channel values)."""
    raw = raw if raw is not None else _run("pactl", "-f", "json", "list", "sink-inputs")
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for s in items:
        p = s.get("properties") or {}
        app = str(p.get("application.name") or "")
        node = str(p.get("node.name") or "")
        media = str(p.get("media.name") or "")
        if s.get("corked") or str(p.get("application.process.id") or "") == str(os.getpid()):
            continue
        if app.lower().startswith(OURS) or node.startswith(("clove_", "bluez_")) or "loopback" in (media + node).lower():
            continue
        vol = [int(str(v.get("value", 0))) for v in (s.get("volume") or {}).values() if isinstance(v, dict)]
        out.append({"index": s["index"], "app": app or node or "an app", "volume": vol})
    return out


def mpris_playing(raw_names: str | None = None) -> bool:
    """Does any media player say it is playing?"""
    names_raw = raw_names if raw_names is not None else _run(
        "busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        "ListNames", "--json=short")
    try:
        names = json.loads(names_raw)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return False
    for name in names:
        if not str(name).startswith("org.mpris.MediaPlayer2."):
            continue
        out = _run("busctl", "--user", "get-property", name, "/org/mpris/MediaPlayer2",
                   "org.mpris.MediaPlayer2.Player", "PlaybackStatus")
        if '"Playing"' in out:
            return True
    return False


class MediaWatch:
    def __init__(self, a):
        self.a = a
        self.playing = False
        self.apps: list[str] = []
        self.seen_since = 0.0             # a foreign stream has been running since (it must last, not a ding)

    def on(self) -> bool:
        prefs = getattr(getattr(self.a, "dashboard", None), "prefs", {}) or {}
        return bool(prefs.get("musicaware", True))

    # ---- what's playing ----------------------------------------------------------------------
    def update(self, streams: list[dict], player_playing: bool, now: float):
        if streams:
            self.seen_since = self.seen_since or now
        else:
            self.seen_since = 0.0
        playing = self.on() and (player_playing or (streams and now - self.seen_since >= 2.0))
        playing = bool(playing)
        if playing != self.playing:
            log.info("media %s%s", "playing" if playing else "stopped",
                     f" ({', '.join(sorted({s['app'] for s in streams}))})" if playing and streams else "")
        self.playing = playing
        self.apps = sorted({s["app"] for s in streams})

    async def run(self):
        while True:
            await asyncio.sleep(POLL_S)
            try:
                streams = await asyncio.to_thread(foreign_streams)
                player = await asyncio.to_thread(mpris_playing) if not streams else False
                self.update(streams, player, time.monotonic())
            except Exception as e:
                log.warning("media watch: %s", e)

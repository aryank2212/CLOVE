"""An out-of-date extension is first asked to reload itself; one too old to do that is reported plainly, never as a
silent failure. Run: .venv/bin/python tests/test_bridge_stale.py"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

config.BRIDGE_PORT = 8798
import websockets  # noqa: E402
import browser_bridge as bb  # noqa: E402


async def main() -> int:
    seen, cmds = [], []
    bb.bridge.on_stale = lambda have, want: seen.append((have, want))
    bb.SELF_RELOAD_WAIT_S = 0.4
    bb.SEEN = Path(tempfile.mkdtemp()) / "seen.txt"
    await bb.bridge.start()
    async with websockets.connect(f"ws://127.0.0.1:{config.BRIDGE_PORT}", origin=bb.ORIGIN) as ws:
        async def old_extension():
            async for raw in ws:
                m = json.loads(raw)
                cmds.append(m.get("cmd"))
                await ws.send(json.dumps({"id": m["id"], "ok": False, "error": f"unknown command {m['cmd']}"}))
        task = asyncio.create_task(old_extension())
        await ws.send(json.dumps({"hello": "clove-hands", "version": "3.1.0"}))     # an old build
        await asyncio.sleep(0.8)
        out = await bb.bridge.call("call_state")
        task.cancel()
    # The same old build reconnecting (its reload didn't help) is not asked again: no reload loop.
    async with websockets.connect(f"ws://127.0.0.1:{config.BRIDGE_PORT}", origin=bb.ORIGIN) as ws:
        await ws.send(json.dumps({"hello": "clove-hands", "version": "3.1.0"}))
        try:
            again = await asyncio.wait_for(ws.recv(), 0.6)
        except asyncio.TimeoutError:
            again = None
    # A newer build than the files on disk (loaded from another folder) is left alone.
    async with websockets.connect(f"ws://127.0.0.1:{config.BRIDGE_PORT}", origin=bb.ORIGIN) as ws:
        await ws.send(json.dumps({"hello": "clove-hands", "version": "99.0.0"}))
        try:
            newer = await asyncio.wait_for(ws.recv(), 0.6)
        except asyncio.TimeoutError:
            newer = None
        newer_stale = bb.bridge.stale
    ok = [("asked to reload itself first", cmds[:1] == ["self_reload"]),
          ("asked once, not again on reconnect", again is None),
          ("a newer extension is not reloaded", newer is None and not newer_stale),
          ("versions compare as numbers", bb.version_key("3.10.0") > bb.version_key("3.9.9")),
          ("remembered as installed", bb.SEEN.exists()),
          ("still old -> user told", bool(seen) and seen[0][0] == "3.1.0"), ("error says to reload", "reload" in out and "out of date" in out),
          ("names both versions", "3.1.0" in out and bb.wanted_version() in out)]
    for k, v in ok:
        print(("PASS " if v else "FAIL ") + k)
    if not all(v for _, v in ok):
        print(out)
    return 0 if all(v for _, v in ok) else 1

sys.exit(asyncio.run(main()))

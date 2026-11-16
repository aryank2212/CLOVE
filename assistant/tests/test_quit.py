"""Quitting CLOVE from Clove Notch (control socket "quit"): the assistant ends, after its answer has gone out."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ctl  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


async def main():
    quit_calls = []
    a = SimpleNamespace(loop=asyncio.get_running_loop(), quit=lambda: quit_calls.append(1))
    reply = await ctl.command(a, "quit")
    check("it answers first", reply == "bye" and not quit_calls)
    await asyncio.sleep(0.4)
    check("then it quits", quit_calls == [1])


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

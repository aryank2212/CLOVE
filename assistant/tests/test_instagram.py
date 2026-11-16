"""Instagram DMs through the official API: only Meta's signed deliveries are taken, the address check answers Meta,
messages come with who sent them, and the browser's anonymous copy is dropped. No network: the API is a stand-in."""
import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import instagram as IG  # noqa: E402
import notifications as N  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


SECRET = "app-secret"
DM = {"object": "instagram", "entry": [{"id": "17841", "time": 1, "messaging": [
    {"sender": {"id": "IGSID1"}, "recipient": {"id": "17841"}, "timestamp": 1, "message": {"mid": "m1", "text": "hey, free tonight?"}},
    {"sender": {"id": "17841"}, "recipient": {"id": "IGSID1"}, "timestamp": 2, "message": {"mid": "m2", "text": "mine", "is_echo": True}},
    {"sender": {"id": "IGSID2"}, "recipient": {"id": "17841"}, "timestamp": 3, "message": {"mid": "m3", "attachments": [{"type": "ig_reel"}]}},
]}]}


def signed(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


# ---- the pieces -------------------------------------------------------------------------------------
body = json.dumps(DM).encode()
check("Meta's signature is accepted", IG.signature_ok(body, signed(body), SECRET))
check("a wrong signature is refused", not IG.signature_ok(body, "sha256=" + "0" * 64, SECRET))
check("no signature is refused", not IG.signature_ok(body, "", SECRET))
got = IG.messages_in(DM)
check("his own messages (echoes) are left out", [m["sender"] for m in got] == ["IGSID1", "IGSID2"])
check("a reel without words says what came", got[1]["text"] == "sent a reel")
check("not Instagram: nothing", IG.messages_in({"object": "page", "entry": []}) == [])


# ---- the webhook, for real (a local server) ---------------------------------------------------------
async def http(port, raw: bytes) -> tuple[int, bytes]:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(raw)
    await w.drain()
    data = await r.read()
    w.close()
    head, _, rest = data.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), rest


async def main():
    config.IG_ACCESS_TOKEN, config.IG_APP_SECRET, config.IG_VERIFY_TOKEN = "tok", SECRET, "my phrase"
    IG.TOKEN_FILE = Path("/nonexistent/instagram_token")
    seen = []
    a = SimpleNamespace(messages=SimpleNamespace(seen_note=lambda n: seen.append(n)))
    ig = IG.Instagram(a)
    IG.profile = lambda igsid: {"IGSID1": {"name": "Priya Sharma", "username": "priya.s"}}.get(igsid, {})
    server = await asyncio.start_server(ig._client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    st, out = await http(port, b"GET /instagram?hub.mode=subscribe&hub.verify_token=my%20phrase&hub.challenge=4242 HTTP/1.1\r\n\r\n")
    check("Meta's address check is answered with its challenge", st == 200 and out == b"4242")
    st, _ = await http(port, b"GET /instagram?hub.mode=subscribe&hub.verify_token=guess&hub.challenge=1 HTTP/1.1\r\n\r\n")
    check("a wrong verify phrase is refused", st == 403)

    def post(b: bytes, sig: str) -> bytes:
        return (f"POST /instagram HTTP/1.1\r\nContent-Type: application/json\r\nX-Hub-Signature-256: {sig}\r\n"
                f"Content-Length: {len(b)}\r\n\r\n").encode() + b
    st, _ = await http(port, post(body, "sha256=" + "f" * 64))
    await asyncio.sleep(0.1)
    check("a forged delivery is refused and nothing reaches CLOVE", st == 403 and seen == [])
    st, _ = await http(port, post(body, signed(body)))
    await asyncio.sleep(0.2)
    check("Meta's delivery is taken", st == 200 and len(seen) == 2)
    check("with their name and @username", seen and seen[0].who == "Priya Sharma (@priya.s)" and seen[0].body == "hey, free tonight?")
    check("someone without a profile is still shown", len(seen) > 1 and seen[1].title == "Someone on Instagram")
    st, _ = await http(port, post(body, signed(body)))
    await asyncio.sleep(0.2)
    check("the same delivery twice is shown once", len(seen) == 2)
    st, _ = await http(port, b"GET /elsewhere HTTP/1.1\r\n\r\n")
    check("anything else on this port: not found", st == 404)

    sent = []
    IG.send = lambda igsid, text: (sent.append((igsid, text)), True)[1]
    check("a reply finds them by name", ig.reply("Priya Sharma", "Hi!").startswith("sent") and sent[-1] == ("IGSID1", "Hi!"))
    check("...or by @username", ig.reply("@priya.s", "Hi again").startswith("sent"))
    check("someone who never wrote: a clear error", ig.reply("nobody", "x").startswith("error"))
    server.close()

    # the browser's copy (no sender) is dropped once the API is set up
    prefs = {"announce": False, "forward": False}
    b = SimpleNamespace(loop=asyncio.get_running_loop(), dashboard=SimpleNamespace(prefs=prefs),
                        dictation=SimpleNamespace(on=False), focus=SimpleNamespace(active=False),
                        calls=SimpleNamespace(audible=lambda: False), instagram=ig, notch=None)
    shown = []
    b.notch = SimpleNamespace(notice=lambda app, kind, who, text="": shown.append((app, who)))
    w = N.Notifications(b)
    w.seen_note(N.Note("Google Chrome", "Instagram", "hey, free tonight?", "Instagram"))
    check("the browser's nameless Instagram copy is not shown", shown == [])
    note = N.Note("Instagram", "Priya Sharma", "hey, free tonight?", "Instagram")
    note.handle, note.igsid = "@priya.s", "IGSID1"
    w.seen_note(note)
    check("the API's copy is, with who sent it", shown == [("Instagram", "Priya Sharma (@priya.s)")])


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)

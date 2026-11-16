// CLOVE fork: the "While you were busy" inbox counts what CLOVE saw: calls it took, calls nobody took,
// messages and its own replies; the newest item is shown.

import { test } from "node:test";
import assert from "node:assert/strict";
import { installFakeDom } from "./fakedom.mjs";

installFakeDom();
const { inboxSummary } = await import("../src/core/state.ts");

const item = (kind, sender, text = "") => ({ app: "WhatsApp", kind, sender, text, at: 0 });

test("nothing in: nothing counted", () => {
  assert.deepEqual(inboxSummary([]), { calls: 0, missed: 0, messages: 0, replied: 0, newest: null });
});

test("a call CLOVE answered is taken, not missed; one nobody answered is missed", () => {
  const s = inboxSummary([
    item("ringing", "Mum"), item("call", "Mum"), item("ended", "Mum", "She'll call back"),
    item("ringing", "+91 98765"),
  ]);
  assert.equal(s.calls, 1);
  assert.equal(s.missed, 1);
});

test("messages and replies are counted; the newest is the last one", () => {
  const s = inboxSummary([item("message", "Aniket", "hi"), item("message", "Aniket", "there?"), item("replied", "Aniket", "Hi, this is CLOVE")]);
  assert.equal(s.messages, 2);
  assert.equal(s.replied, 1);
  assert.equal(s.newest.text, "Hi, this is CLOVE");
});

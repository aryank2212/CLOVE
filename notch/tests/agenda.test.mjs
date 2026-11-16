// The agenda on the notch (src/live/agenda.ts): which day a reminder or an event falls on, and the days
// of a month that have something on them. Keeping and changing them is CLOVE's (assistant/agenda.py).

import { test } from "node:test";
import assert from "node:assert/strict";

const { Agenda, dayKey } = await import("../src/live/agenda.ts");

test("a day is written as YYYY-MM-DD in local time", () => {
  assert.equal(dayKey(new Date(2026, 10, 5, 23, 59)), "2026-11-05");
  assert.equal(dayKey(new Date(2026, 0, 1, 0, 0)), "2026-01-01");
});

test("what falls on a day: its events, the reminders due then, the to-dos dated for it", () => {
  Agenda.events = [
    { title: "Dentist", day: "2026-11-12", time: "10:30", end: "11:00", where: "" },
    { title: "Standup", day: "2026-11-13", time: "09:30", end: "09:45", where: "" },
  ];
  Agenda.reminders = [
    { id: 1, text: "call the bank", at: new Date(2026, 10, 12, 18, 0).getTime() },
    { id: 2, text: "water the plants", at: new Date(2026, 10, 20, 8, 0).getTime() },
  ];
  Agenda.todos = [
    { id: 7, text: "renew passport", due: "2026-11-12" },
    { id: 8, text: "buy milk", due: "" },
  ];
  const day = Agenda.on(new Date(2026, 10, 12, 15, 0));
  assert.deepEqual(day.events.map((e) => e.title), ["Dentist"]);
  assert.deepEqual(day.reminders.map((r) => r.text), ["call the bank"]);
  assert.deepEqual(day.todos.map((t) => t.text), ["renew passport"]);
  assert.deepEqual([...Agenda.busyDays(new Date(2026, 10, 1))].sort((a, b) => a - b), [12, 13, 20]);
  assert.equal(Agenda.busyDays(new Date(2026, 11, 1)).size, 0);
});

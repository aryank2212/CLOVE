// CLOVE fork: the Controls and Time pages' logic (src/core/tools.ts): the timer, the stopwatch, alarms, the
// compact notch's live activity, city clocks and day and night on the map.

import { test } from "node:test";
import assert from "node:assert/strict";
import { installFakeDom } from "./fakedom.mjs";

installFakeDom();
const { Tools, clockText, cityTime, isDay, subsolarPoint } = await import("../src/core/tools.ts");

test("times read like a clock", () => {
  assert.equal(clockText(0), "0:00");
  assert.equal(clockText(272_000), "4:32");
  assert.equal(clockText(3_909_000), "1:05:09");
  assert.equal(clockText(62_340, true), "1:02.3");
});

test("the timer runs, pauses, resumes and resets", () => {
  Tools.timerReset();
  assert.ok(Tools.timerIdle);
  Tools.timerToggle();
  assert.ok(Tools.timerRunning);
  assert.equal(Tools.live()?.kind, "timer");
  Tools.timerToggle();
  assert.ok(!Tools.timerRunning && !Tools.timerIdle);
  assert.equal(Tools.live()?.kind, "timerPaused");
  Tools.timerReset();
  assert.ok(Tools.timerIdle);
});

test("a finished timer rings once and stops", () => {
  Tools.timerReset();
  Tools.timerToggle();
  const later = new Date(Date.now() + Tools.timerDuration + 1000);
  Tools.tick(later);
  assert.equal(Tools.ringing?.kind, "timer");
  assert.equal(Tools.live()?.kind, "ringing");
  assert.ok(!Tools.timerRunning);
  Tools.stopRinging();
  assert.equal(Tools.ringing, null);
});

test("the stopwatch counts, laps and resets", () => {
  Tools.stopwatchToggle();
  assert.ok(Tools.stopwatchRunning);
  Tools.stopwatchLapOrReset();
  assert.equal(Tools.laps.length, 1);
  Tools.stopwatchToggle();
  Tools.stopwatchLapOrReset();
  assert.equal(Tools.laps.length, 0);
  assert.equal(Tools.stopwatchMs(), 0);
});

test("alarms: the next one, and it goes off at its minute", () => {
  for (const a of [...Tools.alarms]) Tools.removeAlarm(a.id);
  const now = new Date(2026, 9, 31, 6, 50);
  Tools.addAlarm(7, 30);
  Tools.addAlarm(6, 0);
  const next = Tools.nextAlarm(now);
  assert.equal(next.alarm.h, 7);
  assert.equal(next.inMin, 40);
  Tools.tick(new Date(2026, 9, 31, 7, 30, 5));
  assert.equal(Tools.ringing?.kind, "alarm");
  assert.equal(Tools.ringing?.label, "07:30");
  Tools.stopRinging();
  for (const a of [...Tools.alarms]) Tools.removeAlarm(a.id);
});

test("city clocks: the time there", () => {
  const at = new Date(Date.UTC(2026, 0, 15, 12, 0));
  assert.equal(cityTime("Asia/Kolkata", at).time, "17:30");
  assert.equal(cityTime("Asia/Tokyo", at).time, "21:00");
  assert.equal(cityTime("Not/AZone", at).time, "--:--");
});

test("day and night: noon UTC is day in London and night in Tokyo... and the sun is over the Atlantic", () => {
  const at = new Date(Date.UTC(2026, 5, 21, 12, 0));
  const sun = subsolarPoint(at);
  assert.ok(Math.abs(sun.lon) < 2);
  assert.ok(sun.lat > 23 && sun.lat < 24);
  assert.ok(isDay(51.5, -0.1, sun));
  assert.ok(!isDay(-35, 140, sun));
});

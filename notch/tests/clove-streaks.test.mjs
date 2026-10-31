// CLOVE fork: streak math (src/core/streaks.ts): totals, best day, longest and current streaks, the 53-week grid.

import { test } from "node:test";
import assert from "node:assert/strict";
import { installFakeDom } from "./fakedom.mjs";

installFakeDom();
const { stats, merge, fromStamps, fromActivity, dayKey } = await import("../src/core/streaks.ts");

const today = new Date(2026, 9, 31);            // Saturday 31 Oct 2026
const day = (n) => dayKey(new Date(2026, 9, 31 - n));

test("totals, best day, average", () => {
  const s = stats(new Map([[day(0), 3], [day(1), 7], [day(400), 99]]), today);
  assert.equal(s.total, 10);                     // the day 400 days ago is outside the year
  assert.equal(s.best, 7);
  assert.equal(s.bestDate, day(1));
  assert.ok(s.average > 0 && s.average < 1);
});

test("current streak runs to today, or to yesterday while today is still empty", () => {
  const withToday = stats(new Map([[day(0), 1], [day(1), 1], [day(2), 1], [day(4), 1]]), today);
  assert.equal(withToday.current, 3);
  assert.equal(withToday.currentFrom, day(2));
  const notYet = stats(new Map([[day(1), 1], [day(2), 1]]), today);
  assert.equal(notYet.current, 2);
  const broken = stats(new Map([[day(2), 1]]), today);
  assert.equal(broken.current, 0);
});

test("longest streak with its dates", () => {
  const m = new Map();
  for (let i = 10; i <= 14; i++) m.set(day(i), 1);
  m.set(day(1), 1);
  const s = stats(m, today);
  assert.equal(s.longest, 5);
  assert.equal(s.longestFrom, day(14));
  assert.equal(s.longestTo, day(10));
});

test("a 53-week grid, Sunday on top, nothing past today", () => {
  const s = stats(new Map(), today);
  assert.equal(s.weeks.length, 53);
  assert.ok(s.weeks.every((w) => w.length === 7));
  assert.equal(new Date(s.weeks[0][0].date).getUTCDay(), 0);
  const last = s.weeks[52];
  assert.equal(last[6]?.date, day(0));           // Saturday is today: the last cell
});

test("levels follow quartiles; zero stays zero", () => {
  const m = new Map([[day(0), 1], [day(1), 2], [day(2), 5], [day(3), 20]]);
  const cells = stats(m, today).weeks.flat().filter(Boolean);
  const lv = (d) => cells.find((c) => c.date === d).level;
  assert.equal(lv(day(5)), 0);
  assert.ok(lv(day(3)) === 4 && lv(day(0)) <= lv(day(1)) && lv(day(1)) <= lv(day(2)));
});

test("sources: a connected calendar, LeetCode moments on local days, all together", () => {
  const a = fromActivity({ total: 3, weeks: [[{ date: day(0), count: 2, level: 1, weekday: 6 }, { date: day(1), count: 1, level: 1, weekday: 5 }]], fetchedAt: 0 });
  assert.equal(a.get(day(0)), 2);
  assert.equal(fromActivity(null), null);
  const noon = new Date(2026, 9, 31, 12).getTime() / 1000;
  const lc = fromStamps([[noon, 4]]);
  assert.equal(lc.get(day(0)), 4);
  assert.equal(merge([a, lc]).get(day(0)), 6);
});

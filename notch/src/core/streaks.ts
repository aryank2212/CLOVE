// CLOVE fork: contribution streaks for the StandBy cards.
//
// GitHub and Gitea come from their connections: integrations.rs already reads each one's contribution calendar
// (State.integrations[id].data.activity). LeetCode has no sign-in, so its connection is his user name; its public
// submission calendar is read through Rust (streaks.rs) every 30 minutes. Everything is counted on his local days.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "./bridge";
import type { GitHubActivity } from "./github";
import { State } from "./state";

export type StreakSource = "github" | "gitea" | "leetcode";
export const SOURCES: StreakSource[] = ["github", "gitea", "leetcode"];
export const SOURCE_NAMES: Record<StreakSource, string> = { github: "GitHub", gitea: "Gitea", leetcode: "LeetCode" };
export const SOURCE_PILL: Record<StreakSource, string> = {
  github: "integration_github", gitea: "integration_gitea", leetcode: "",
};

/** One local day: "YYYY-MM-DD" → contributions. */
export type DayCounts = Map<string, number>;

export interface StreakStats {
  total: number;
  best: number;
  bestDate: string | null;
  average: number;
  longest: number;
  longestFrom: string | null;
  longestTo: string | null;
  current: number;
  currentFrom: string | null;
  /** 53 columns (weeks, oldest first, Sunday on top) of 7 cells: {date, count, level 0–4}; null past today. */
  weeks: ({ date: string; count: number; level: number } | null)[][];
  /** The first and last day counted. */
  from: string;
  to: string;
}

export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

/** A connected GitHub or Gitea calendar as day counts. */
export function fromActivity(a: GitHubActivity | null | undefined): DayCounts | null {
  if (!a?.weeks?.length) return null;
  const out: DayCounts = new Map();
  for (const w of a.weeks) for (const d of w) if (d?.date) out.set(d.date, (out.get(d.date) ?? 0) + (d.count ?? 0));
  return out;
}

/** Unix-second moments (LeetCode) as his local days. */
export function fromStamps(stamps: [number, number][]): DayCounts {
  const out: DayCounts = new Map();
  for (const [ts, n] of stamps) {
    const k = dayKey(new Date(ts * 1000));
    out.set(k, (out.get(k) ?? 0) + n);
  }
  return out;
}

export function merge(maps: DayCounts[]): DayCounts {
  const out: DayCounts = new Map();
  for (const m of maps) for (const [k, n] of m) out.set(k, (out.get(k) ?? 0) + n);
  return out;
}

/** The last year (53 weeks to today) of `days`, its totals and its streaks. */
export function stats(days: DayCounts, today = new Date()): StreakStats {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  // The grid starts on the Sunday 52 weeks before this week's Sunday.
  const start = addDays(end, -end.getDay() - 52 * 7);
  const counts: { date: string; count: number }[] = [];
  for (let d = start; d <= end; d = addDays(d, 1)) counts.push({ date: dayKey(d), count: days.get(dayKey(d)) ?? 0 });

  let total = 0, best = 0, bestDate: string | null = null;
  let longest = 0, longestFrom: string | null = null, longestTo: string | null = null;
  let run = 0, runFrom: string | null = null;
  for (const c of counts) {
    total += c.count;
    if (c.count > best) { best = c.count; bestDate = c.date; }
    if (c.count > 0) {
      if (run === 0) runFrom = c.date;
      run++;
      if (run > longest) { longest = run; longestFrom = runFrom; longestTo = c.date; }
    } else {
      run = 0;
    }
  }
  // The current streak: up to today, or up to yesterday while today has nothing yet.
  let current = 0, currentFrom: string | null = null;
  let i = counts.length - 1;
  if (i >= 0 && counts[i].count === 0) i--;
  for (; i >= 0 && counts[i].count > 0; i--) { current++; currentFrom = counts[i].date; }

  // Levels by quartiles of the days with something, like GitHub's.
  const nonzero = counts.map((c) => c.count).filter((n) => n > 0).sort((a, b) => a - b);
  const q = (p: number) => nonzero[Math.floor(p * (nonzero.length - 1))] ?? 0;
  const q1 = q(0.25), q2 = q(0.5), q3 = q(0.75);
  const level = (n: number) => (n <= 0 ? 0 : n <= q1 ? 1 : n <= q2 ? 2 : n <= q3 ? 3 : 4);
  const weeks: StreakStats["weeks"] = [];
  for (let w = 0; w < 53; w++) {
    const col: StreakStats["weeks"][number] = [];
    for (let d = 0; d < 7; d++) {
      const c = counts[w * 7 + d];
      col.push(c ? { ...c, level: level(c.count) } : null);
    }
    weeks.push(col);
  }
  return {
    total, best, bestDate, average: counts.length ? total / counts.length : 0,
    longest, longestFrom, longestTo, current, currentFrom, weeks,
    from: counts[0]?.date ?? dayKey(end), to: dayKey(end),
  };
}

// ── The sources ─────────────────────────────────────────────────────────────────

const LC_KEY = "clove-leetcode-v1";

interface LeetCodeSaved {
  user: string;
  stamps: [number, number][];
  at: number;
  error: string;
}

function loadLc(): LeetCodeSaved {
  try {
    const raw = globalThis.localStorage?.getItem(LC_KEY);
    if (raw) return { user: "", stamps: [], at: 0, error: "", ...JSON.parse(raw) };
  } catch { /* nothing kept */ }
  return { user: "", stamps: [], at: 0, error: "" };
}

class StreaksState {
  private lc: LeetCodeSaved = loadLc();
  private loading = false;

  private saveLc() {
    try {
      globalThis.localStorage?.setItem(LC_KEY, JSON.stringify(this.lc));
    } catch { /* kept for this run */ }
  }

  get leetcodeUser(): string {
    return this.lc.user;
  }
  get leetcodeError(): string {
    return this.lc.error;
  }
  get loadingLeetcode(): boolean {
    return this.loading;
  }

  /** Connects LeetCode by user name ("" disconnects). */
  async setLeetcode(user: string) {
    this.lc = { user: user.trim().replace(/^@/, ""), stamps: [], at: 0, error: "" };
    this.saveLc();
    State.notify();
    if (this.lc.user) await this.refreshLeetcode(true);
  }

  async refreshLeetcode(force = false) {
    if (!this.lc.user || this.loading || !IS_TAURI) return;
    if (!force && Date.now() - this.lc.at < 30 * 60_000) return;
    this.loading = true;
    State.notify();
    try {
      const data = await invoke<{ stamps: [number, number][] }>("streaks_fetch", { user: this.lc.user });
      this.lc = { ...this.lc, stamps: data.stamps ?? [], at: Date.now(), error: "" };
    } catch (e) {
      this.lc = { ...this.lc, at: Date.now(), error: String(e).slice(0, 120) };
    } finally {
      this.loading = false;
      this.saveLc();
      State.notify();
    }
  }

  /** Is the source connected (GitHub/Gitea: their pill is on and has a calendar; LeetCode: a user name)? */
  connected(src: StreakSource): boolean {
    if (src === "leetcode") return !!this.lc.user;
    return this.days(src) != null;
  }

  days(src: StreakSource): DayCounts | null {
    if (!IS_TAURI && src !== "gitea") return demoDays(src);       // `npm run dev` only: something to look at
    if (src === "leetcode") return this.lc.user ? fromStamps(this.lc.stamps) : null;
    const info = State.integrations[SOURCE_PILL[src]];
    const activity = (info?.data as { activity?: GitHubActivity } | undefined)?.activity;
    return fromActivity(activity);
  }

  /** All connected sources together. */
  combined(): DayCounts | null {
    const maps = SOURCES.map((s) => this.days(s)).filter((m): m is DayCounts => m != null);
    return maps.length ? merge(maps) : null;
  }
}

export const Streaks = new StreaksState();

/** A made-up year for the plain-browser preview (never in the app: Tauri always has the real sources). */
function demoDays(src: StreakSource): DayCounts {
  const out: DayCounts = new Map();
  let seed = src === "github" ? 7 : 3;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const today = new Date();
  for (let i = 0; i < 371; i++) {
    const r = rnd();
    if (i < 16 || r > 0.35) out.set(dayKey(addDays(today, -i)), Math.floor(rnd() * (src === "github" ? 12 : 4)) + 1);
  }
  return out;
}

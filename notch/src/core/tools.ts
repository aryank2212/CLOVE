// CLOVE fork: the Controls and Time pages' state — the four quick toggles, the music playing, the timer, the
// stopwatch, the alarms and the world clocks — and the "live activity" the compact notch shows while one runs.
//
// Timer, stopwatch and alarms live here, in the page (kept in localStorage, so they survive a restart of Clove
// Notch). The toggles and the music come from Rust (controls.rs), asked only while a page shows them or while a
// recording runs.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "./bridge";
import { Sound } from "./sound";
import { State } from "./state";

export interface ControlsStatus {
  awake: boolean;
  nightlight: boolean;
  recording: boolean;
}

export interface MediaState {
  player: string;
  title: string;
  artist: string;
  playing: boolean;
  position: number;
  length: number;
  art: string;
}

export interface Alarm {
  id: number;
  h: number;
  m: number;
  on: boolean;
}

export interface City {
  name: string;
  zone: string;
  lat: number;
  lon: number;
}

export type ClockTab = "timer" | "stopwatch" | "alarm";

/** What the compact notch shows instead of the clock while something runs (most urgent first). */
export type LiveActivity =
  | { kind: "ringing"; label: string }
  | { kind: "recording"; since: number }
  | { kind: "timer"; endAt: number; paused: false }
  | { kind: "timerPaused"; left: number }
  | { kind: "stopwatch"; ms: number; running: boolean }
  | { kind: "media"; title: string; artist: string; playing: boolean }
  | null;

export const DEFAULT_CITIES: City[] = [
  { name: "New Delhi", zone: "Asia/Kolkata", lat: 28.6, lon: 77.2 },
  { name: "London", zone: "Europe/London", lat: 51.5, lon: -0.1 },
  { name: "New York", zone: "America/New_York", lat: 40.7, lon: -74.0 },
  { name: "San Francisco", zone: "America/Los_Angeles", lat: 37.8, lon: -122.4 },
  { name: "Tokyo", zone: "Asia/Tokyo", lat: 35.7, lon: 139.7 },
  { name: "Dubai", zone: "Asia/Dubai", lat: 25.2, lon: 55.3 },
];

const KEY = "clove-tools-v1";

interface Saved {
  timerDuration: number;
  timerEndAt: number | null;
  timerLeft: number;
  /** Started and not yet reset or finished (paused counts). */
  timerStarted: boolean;
  swStartAt: number | null;
  swAcc: number;
  laps: number[];
  alarms: Alarm[];
  clockTab: ClockTab;
}

function load(): Saved {
  const fallback: Saved = {
    timerDuration: 5 * 60_000, timerEndAt: null, timerLeft: 5 * 60_000, timerStarted: false,
    swStartAt: null, swAcc: 0, laps: [], alarms: [], clockTab: "timer",
  };
  try {
    const raw = globalThis.localStorage?.getItem(KEY);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!IS_TAURI) return null;
  try {
    return await invoke<T>(cmd, args);
  } catch {
    return null;
  }
}

class ToolsState {
  status: ControlsStatus = { awake: false, nightlight: false, recording: false };
  recordingSince: number | null = null;
  media: MediaState | null = null;
  /** When `media.position` was read (ms), so the bar runs on between reads. */
  mediaAt = 0;
  ringing: { kind: "timer" | "alarm"; label: string } | null = null;
  /** Called when a timer ends or an alarm goes off (the island opens on the Controls page). */
  onRing: (() => void) | null = null;
  cities: City[] = DEFAULT_CITIES;

  private s: Saved = load();
  private lastAlarmMinute = "";
  private ringTimer: ReturnType<typeof setInterval> | null = null;

  private save() {
    try {
      globalThis.localStorage?.setItem(KEY, JSON.stringify(this.s));
    } catch {
      /* private mode: kept for this run only */
    }
  }

  // ── toggles ─────────────────────────────────────────────────────────────────
  async refreshStatus() {
    const s = await call<ControlsStatus>("controls_status");
    if (s) this.setStatus(s);
  }

  async act(action: "screenshot" | "record" | "awake" | "nightlight") {
    // Optimistic: the tile flips at once; Rust's answer settles it.
    if (action === "awake") this.status = { ...this.status, awake: !this.status.awake };
    if (action === "nightlight") this.status = { ...this.status, nightlight: !this.status.nightlight };
    State.notify();
    const s = await call<ControlsStatus>("controls_action", { action });
    if (s) this.setStatus(s);
  }

  private setStatus(s: ControlsStatus) {
    if (s.recording && !this.status.recording) this.recordingSince = Date.now();
    if (!s.recording) this.recordingSince = null;
    this.status = s;
    State.notify();
  }

  // ── music ───────────────────────────────────────────────────────────────────
  async refreshMedia() {
    const m = await call<MediaState | null>("media_state");
    this.media = m ?? null;
    this.mediaAt = Date.now();
    State.notify();
  }

  async mediaControl(action: "toggle" | "next" | "previous") {
    if (action === "toggle" && this.media) {
      this.media = { ...this.media, playing: !this.media.playing, position: this.mediaPosition() };
      this.mediaAt = Date.now();
      State.notify();
    }
    await call<boolean>("media_control", { action });
    window.setTimeout(() => void this.refreshMedia(), action === "toggle" ? 300 : 600);
  }

  mediaPosition(now = Date.now()): number {
    const m = this.media;
    if (!m) return 0;
    const p = m.position + (m.playing ? (now - this.mediaAt) / 1000 : 0);
    return m.length > 0 ? Math.min(p, m.length) : p;
  }

  // ── timer ───────────────────────────────────────────────────────────────────
  get clockTab(): ClockTab {
    return this.s.clockTab;
  }
  set clockTab(t: ClockTab) {
    this.s.clockTab = t;
    this.save();
    State.notify();
  }

  timerLeft(now = Date.now()): number {
    return this.s.timerEndAt != null ? Math.max(0, this.s.timerEndAt - now) : this.s.timerLeft;
  }
  get timerRunning(): boolean {
    return this.s.timerEndAt != null;
  }
  get timerDuration(): number {
    return this.s.timerDuration;
  }
  /** Set aside (not running, and not started). */
  get timerIdle(): boolean {
    return !this.s.timerStarted;
  }

  timerToggle() {
    if (this.s.timerEndAt != null) {
      this.s.timerLeft = this.timerLeft();
      this.s.timerEndAt = null;
    } else {
      if (this.s.timerLeft <= 0) this.s.timerLeft = this.s.timerDuration;
      this.s.timerEndAt = Date.now() + this.s.timerLeft;
      this.s.timerStarted = true;
    }
    this.save();
    State.notify();
  }

  timerReset() {
    this.s.timerEndAt = null;
    this.s.timerStarted = false;
    this.s.timerLeft = this.s.timerDuration;
    this.save();
    State.notify();
  }

  /** Adds (or, negative, takes) minutes: to the set time while idle, to what's left while running. */
  timerAdd(minutes: number) {
    const ms = minutes * 60_000;
    if (this.s.timerEndAt != null) {
      this.s.timerEndAt = Math.max(Date.now() + 1000, this.s.timerEndAt + ms);
    } else if (this.timerIdle) {
      this.s.timerDuration = Math.min(24 * 3600_000, Math.max(60_000, this.s.timerDuration + ms));
      this.s.timerLeft = this.s.timerDuration;
    } else {
      this.s.timerLeft = Math.max(1000, this.s.timerLeft + ms);
    }
    this.save();
    State.notify();
  }

  // ── stopwatch ───────────────────────────────────────────────────────────────
  stopwatchMs(now = Date.now()): number {
    return this.s.swAcc + (this.s.swStartAt != null ? now - this.s.swStartAt : 0);
  }
  get stopwatchRunning(): boolean {
    return this.s.swStartAt != null;
  }
  get laps(): number[] {
    return this.s.laps;
  }

  stopwatchToggle() {
    if (this.s.swStartAt != null) {
      this.s.swAcc = this.stopwatchMs();
      this.s.swStartAt = null;
    } else {
      this.s.swStartAt = Date.now();
    }
    this.save();
    State.notify();
  }

  /** Running: a lap. Stopped: back to zero. */
  stopwatchLapOrReset() {
    if (this.s.swStartAt != null) {
      this.s.laps = [this.stopwatchMs(), ...this.s.laps].slice(0, 20);
    } else {
      this.s.swAcc = 0;
      this.s.laps = [];
    }
    this.save();
    State.notify();
  }

  // ── alarms ──────────────────────────────────────────────────────────────────
  get alarms(): Alarm[] {
    return this.s.alarms;
  }

  addAlarm(h: number, m: number) {
    const id = Date.now();
    this.s.alarms = [...this.s.alarms, { id, h, m, on: true }]
      .sort((a, b) => a.h * 60 + a.m - (b.h * 60 + b.m))
      .slice(0, 6);
    this.save();
    State.notify();
  }

  toggleAlarm(id: number) {
    this.s.alarms = this.s.alarms.map((a) => (a.id === id ? { ...a, on: !a.on } : a));
    this.save();
    State.notify();
  }

  removeAlarm(id: number) {
    this.s.alarms = this.s.alarms.filter((a) => a.id !== id);
    this.save();
    State.notify();
  }

  /** The next alarm that is on, as minutes from now (for "in 7 h 20 min"). */
  nextAlarm(now = new Date()): { alarm: Alarm; inMin: number } | null {
    const nowMin = now.getHours() * 60 + now.getMinutes();
    let best: { alarm: Alarm; inMin: number } | null = null;
    for (const a of this.s.alarms) {
      if (!a.on) continue;
      let d = a.h * 60 + a.m - nowMin;
      if (d <= 0) d += 24 * 60;
      if (!best || d < best.inMin) best = { alarm: a, inMin: d };
    }
    return best;
  }

  // ── ringing ─────────────────────────────────────────────────────────────────
  private ring(kind: "timer" | "alarm", label: string) {
    this.ringing = { kind, label };
    this.onRing?.();
    Sound.play("question");
    if (this.ringTimer) clearInterval(this.ringTimer);
    let n = 0;
    this.ringTimer = setInterval(() => {
      // Two minutes at most, then it stops by itself.
      if (!this.ringing || ++n > 60) return this.stopRinging();
      Sound.play("question");
    }, 2000);
    State.notify();
  }

  stopRinging() {
    this.ringing = null;
    if (this.ringTimer) clearInterval(this.ringTimer);
    this.ringTimer = null;
    State.notify();
  }

  /** Once a second (main.ts): ends the timer, sets off alarms. Returns whether anything is live (to redraw). */
  tick(now = new Date()): boolean {
    const t = now.getTime();
    if (this.s.timerEndAt != null && t >= this.s.timerEndAt) {
      this.s.timerEndAt = null;
      this.s.timerStarted = false;
      this.s.timerLeft = this.s.timerDuration;
      this.save();
      this.ring("timer", "");
    }
    const minute = `${now.getHours()}:${now.getMinutes()}`;
    if (minute !== this.lastAlarmMinute) {
      this.lastAlarmMinute = minute;
      const due = this.s.alarms.find((a) => a.on && a.h === now.getHours() && a.m === now.getMinutes());
      if (due) this.ring("alarm", `${String(due.h).padStart(2, "0")}:${String(due.m).padStart(2, "0")}`);
    }
    return this.live() != null;
  }

  live(now = Date.now()): LiveActivity {
    if (this.ringing) return { kind: "ringing", label: this.ringing.label };
    if (this.status.recording && this.recordingSince != null) return { kind: "recording", since: this.recordingSince };
    if (this.s.timerEndAt != null) return { kind: "timer", endAt: this.s.timerEndAt, paused: false };
    if (this.s.timerStarted && this.s.timerLeft > 0) return { kind: "timerPaused", left: this.s.timerLeft };
    if (this.s.swStartAt != null) return { kind: "stopwatch", ms: this.stopwatchMs(now), running: true };
    if (this.media?.playing) return { kind: "media", title: this.media.title, artist: this.media.artist, playing: true };
    return null;
  }
}

export const Tools = new ToolsState();

/** 1:05:09, 4:32, 0:07 — or with tenths for the stopwatch. */
export function clockText(ms: number, tenths = false): string {
  const total = Math.max(0, ms);
  const s = Math.floor(total / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const base = h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  return tenths ? `${base}.${Math.floor((total % 1000) / 100)}` : base;
}

/** The time in a city now, "14:05", and its offset from here in hours ("+5:30", "−9", "" when the same). */
export function cityTime(zone: string, now = new Date()): { time: string; offset: string; hour: number } {
  let time = "";
  let hour = 0;
  try {
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(now);
    const hh = parts.find((p) => p.type === "hour")?.value ?? "00";
    const mm = parts.find((p) => p.type === "minute")?.value ?? "00";
    time = `${hh}:${mm}`;
    hour = Number(hh) + Number(mm) / 60;
  } catch {
    return { time: "--:--", offset: "", hour: 0 };
  }
  const there = zoneOffsetMin(zone, now);
  const here = -now.getTimezoneOffset();
  const d = there - here;
  if (d === 0) return { time, offset: "", hour };
  const sign = d > 0 ? "+" : "−";
  const a = Math.abs(d);
  const offset = `${sign}${Math.floor(a / 60)}${a % 60 ? `:${String(a % 60).padStart(2, "0")}` : ""}`;
  return { time, offset, hour };
}

/** A zone's UTC offset in minutes at `now`. */
export function zoneOffsetMin(zone: string, now = new Date()): number {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(now);
    const v = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
    const asUtc = Date.UTC(v("year"), v("month") - 1, v("day"), v("hour") % 24, v("minute"));
    return Math.round((asUtc - Math.floor(now.getTime() / 60_000) * 60_000) / 60_000);
  } catch {
    return 0;
  }
}

/** Where the sun is overhead now: its latitude (declination) and longitude, in degrees. For the day/night map. */
export function subsolarPoint(now = new Date()): { lat: number; lon: number } {
  const start = Date.UTC(now.getUTCFullYear(), 0, 0);
  const day = (now.getTime() - start) / 86_400_000;
  const lat = -23.44 * Math.cos(((2 * Math.PI) / 365) * (day + 10));
  const utcHours = now.getUTCHours() + now.getUTCMinutes() / 60 + now.getUTCSeconds() / 3600;
  const lon = (12 - utcHours) * 15;
  return { lat, lon: ((lon + 540) % 360) - 180 };
}

/** Is it day at (lat, lon)? (The sun above the horizon there.) */
export function isDay(lat: number, lon: number, sun: { lat: number; lon: number }): boolean {
  const r = Math.PI / 180;
  const cos = Math.sin(lat * r) * Math.sin(sun.lat * r) + Math.cos(lat * r) * Math.cos(sun.lat * r) * Math.cos((lon - sun.lon) * r);
  return cos > 0;
}

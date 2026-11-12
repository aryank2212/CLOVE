// Live Activities on the page: what Rust reports (src-tauri/src/live), what the
// CLOVE assistant or a script pushes over the socket, and what the user starts
// from the cards, turned into the activities of src/core/live.ts. Timers,
// watchlists and orders in progress are kept across restarts.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI, onEvent } from "../core/bridge";
import {
  Live, brandById, classifyNotification, linkOf, followedMatches, is, mergeStage, parseBars, parseDuration, parseQuote,
  parseRoute, parseScoreboard, quoteCandidates, timerLeft,
  type AuthData, type CallData, type DeliveryData, type DesktopNotification, type LiveActivity, type MediaData,
  type NavData, type PaymentData, type RideData, type SportsData, type StockData, type TimerData, type VoiceData,
} from "../core/live";
import { Sound } from "../core/sound";
import { State } from "../core/state";
import { Tools } from "../core/tools";

// ── What Rust sends ───────────────────────────────────────────────────────────

export interface SystemSnapshot {
  mic: string[];
  camera: string[];
  screen: { app: string; pid: number; since: number }[];
  battery: { present: boolean; percent: number; charging: boolean; plugged: boolean };
  devices: { id: string; name: string; kind: string; percent: number | null; charging: boolean }[];
  hotspot: { name: string; ssid: string; iface: string; clients: number } | null;
  locked: boolean;
}

type Player = MediaData & { url: string };

export interface LiveHost {
  /** Opens the activity's card for a moment, then folds back (a banner). */
  banner(id: string, ms: number): void;
  /** Opens the live view on an activity and keeps it open. */
  show(id: string | null): void;
  /** Compact island from hidden, without the peek sound. */
  revealSilently(): void;
}

interface Prefs {
  watchlist: string[];
  follows: string[];
  sport: string;
  /** Matches taken off the notch by hand (their ids): they stay off though their team is followed. */
  hidden: string[];
  /** Where routes start from when no origin is given. */
  home: { name: string; lon: number; lat: number } | null;
}

interface Saved {
  prefs: Prefs;
  activities: LiveActivity[];
}

const STORE_KEY = "clove.live.v1";
const DEFAULT_PREFS: Prefs = { watchlist: [], follows: [], sport: "cricket", hidden: [], home: null };
/** What survives a restart: things that are still true tomorrow. */
const PERSISTED = new Set(["timer", "delivery", "ride", "nav"]);

let host: LiveHost | null = null;
let system: SystemSnapshot | null = null;
let players: Player[] = [];
let artwork: { artUrl: string; dataUrl: string } | null = null;
let prefs: Prefs = { ...DEFAULT_PREFS };
/** The player the media card follows, once the user picked or it started. */
let mediaBus: string | null = null;
let allMatches: SportsData[] = [];
let quotesAt = 0;
let scoresAt = 0;
/** Why the last thing asked from a card did not work, shown on the hub. */
let lastError = "";

const now = () => Date.now();

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!IS_TAURI) return null;
  try {
    return await invoke<T>(cmd, args);
  } catch (err) {
    console.error(`[clove-notch] ${cmd} failed`, err);
    return null;
  }
}

async function fetchJson(kind: string, arg = ""): Promise<unknown> {
  const text = await call<string>("live_fetch", { kind, arg });
  if (text == null) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ── Persistence ───────────────────────────────────────────────────────────────

function save() {
  try {
    const activities = Live.all().filter((a) => PERSISTED.has(a.kind) && a.id !== TOOLS_TIMER);
    localStorage.setItem(STORE_KEY, JSON.stringify({ prefs, activities } satisfies Saved));
  } catch {
    // Private mode or a full disk: the activities still work until the restart.
  }
}

function load() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw) as Partial<Saved>;
    prefs = { ...DEFAULT_PREFS, ...(saved.prefs ?? {}) };
    const t = now();
    for (const a of saved.activities ?? []) {
      if (!a || !PERSISTED.has(a.kind) || (a.expiresAt != null && a.expiresAt <= t)) continue;
      // An order from days ago is over, whatever its last message said.
      if ((a.kind === "delivery" || a.kind === "ride") && t - a.updatedAt > 36 * 3600_000) continue;
      Live.upsert(a.id, a.kind, a.data as never, a.startedAt);
      if (a.expiresAt != null) Live.expire(a.id, a.expiresAt);
    }
  } catch {
    prefs = { ...DEFAULT_PREFS };
  }
}

// ── Media ─────────────────────────────────────────────────────────────────────

function applyPlayers(next: Player[]) {
  const wasPlaying = is(Live.get("media"), "media") && Live.get("media", "media")!.data.playing;
  players = next;
  // Whoever plays wins; among several, the one already followed, else the newest.
  const playing = next.filter((p) => p.playing);
  const followed = next.find((p) => p.bus === mediaBus);
  const pick = playing.find((p) => p.bus === mediaBus) ?? playing[0] ?? followed ?? next[0] ?? null;
  if (!pick) {
    mediaBus = null;
    Live.remove("media");
    return;
  }
  mediaBus = pick.bus;
  Live.upsert("media", "media", pick, now());
  // A paused player steps aside after a while: nothing is "now playing".
  if (!pick.playing) Live.expire("media", now() + 10 * 60_000);
  if (!wasPlaying && pick.playing && State.mode === "hidden" && !State.paused) host?.revealSilently();
}

// ── The machine ───────────────────────────────────────────────────────────────

function applySystem(next: SystemSnapshot) {
  const prev = system;
  system = next;
  const t = now();

  // Screen recordings: one activity per recorder.
  const live = new Set(next.screen.map((r) => `recording:${r.pid}`));
  for (const a of Live.ofKind("recording")) if (!live.has(a.id)) Live.remove(a.id);
  for (const r of next.screen) {
    const id = `recording:${r.pid}`;
    if (!Live.get(id)) Live.upsert(id, "recording", { app: r.app, pid: r.pid, since: r.since || t }, t);
  }

  if (next.camera.length) Live.upsert("camera", "camera", { apps: next.camera }, t);
  else Live.remove("camera");

  if (next.hotspot) {
    const fresh = Live.upsert("hotspot", "hotspot", { ssid: next.hotspot.ssid, iface: next.hotspot.iface, clients: next.hotspot.clients }, t);
    if (fresh && prev) host?.banner("hotspot", 3500);
  } else {
    Live.remove("hotspot");
  }

  // The first report only describes; from then on a change is an event.
  if (prev) {
    const b = next.battery;
    const pb = prev.battery;
    if (b.present) {
      const crossed = (level: number) => !b.charging && !b.plugged && b.percent <= level && pb.percent > level;
      if (b.plugged && !pb.plugged) batteryBanner(b.percent, b.charging || b.plugged, "charging");
      else if (!b.plugged && pb.plugged) batteryBanner(b.percent, false, "unplugged");
      else if (crossed(20) || crossed(10) || crossed(5)) batteryBanner(b.percent, false, "low");
      else if (b.plugged && b.percent >= 100 && pb.percent < 100) batteryBanner(100, true, "full");
    }
    const known = new Set(prev.devices.map((d) => d.id));
    for (const d of next.devices) {
      const before = prev.devices.find((x) => x.id === d.id);
      const lowNow = d.percent != null && d.percent <= 15 && (before?.percent ?? 100) > 15;
      if (!known.has(d.id) || lowNow) {
        Live.upsert(`device:${d.id}`, "device", { name: d.name, type: d.kind as never, percent: d.percent, charging: d.charging }, t, 5000);
        host?.banner(`device:${d.id}`, 4000);
        if (!known.has(d.id)) Sound.play("pop");
      }
    }
    if (prev.locked && !next.locked) authBanner({ method: "unlock", ok: true, detail: "Unlocked" });
  }
  State.notify();
}

function batteryBanner(percent: number, charging: boolean, event: "low" | "charging" | "full" | "unplugged") {
  Live.upsert("battery", "battery", { percent, charging, event }, now(), event === "low" ? 6500 : 4000);
  host?.banner("battery", event === "low" ? 6000 : 3500);
  if (event === "low") Sound.play("question");
}

function authBanner(data: AuthData) {
  // Still checking: stays until the verdict (or half a minute at most).
  const ttl = data.ok == null ? 30_000 : 2600;
  Live.upsert("auth", "auth", data, now(), ttl);
  host?.banner("auth", ttl - 200);
  if (data.ok === true) Sound.play("approve");
  else if (data.ok === false) Sound.play("error");
}

// ── Notifications ─────────────────────────────────────────────────────────────

function applyNotification(n: DesktopNotification) {
  const t = now();
  const hit = classifyNotification(n, t);
  if (!hit) return;
  switch (hit.kind) {
    case "call":
      applyCall(hit.data);
      break;
    case "ride": {
      const old = Live.get(hit.id, "ride")?.data;
      const data = mergeStage<RideData>(old, hit.data);
      Live.upsert(hit.id, "ride", data, t);
      if (data.stage >= 4) Live.expire(hit.id, t + 10 * 60_000);
      if (!old || old.stage !== data.stage) host?.banner(hit.id, 5000);
      break;
    }
    case "delivery": {
      const old = Live.get(hit.id, "delivery")?.data;
      const data = mergeStage<DeliveryData>(old, hit.data);
      Live.upsert(hit.id, "delivery", data, t);
      if (data.stage >= 3) Live.expire(hit.id, t + 30 * 60_000);
      if (!old || old.stage !== data.stage) host?.banner(hit.id, 5000);
      break;
    }
    case "cancel":
      Live.remove(hit.id);
      break;
    case "payment":
      applyPayment(hit.data);
      break;
    case "nav": {
      const old = Live.get("nav", "nav")?.data;
      // A route of our own keeps its steps; the phone's replaces a phone's.
      if (old && old.source === "route") break;
      Live.upsert("nav", "nav", {
        destination: hit.eta || "Navigation", origin: "", steps: [{ text: hit.instruction, distance: 0, modifier: modifierOf(hit.instruction) }],
        stepIndex: 0, distance: 0, duration: 0, etaAt: 0, line: [], source: "phone",
      }, t, 5 * 60_000);
      break;
    }
  }
  save();
}

function modifierOf(text: string): string {
  const s = text.toLowerCase();
  if (s.includes("u-turn")) return "uturn";
  if (s.includes("roundabout")) return "roundabout";
  if (s.includes("arrive") || s.includes("destination")) return "arrive";
  if (s.includes("slight left") || s.includes("keep left")) return "slight left";
  if (s.includes("slight right") || s.includes("keep right")) return "slight right";
  if (s.includes("left")) return "left";
  if (s.includes("right")) return "right";
  return "straight";
}

function applyPayment(data: PaymentData) {
  Live.upsert("payment", "payment", data, now(), 5200);
  host?.banner("payment", 4800);
  Sound.play("approve");
}

function applyCall(data: CallData) {
  const t = now();
  const old = Live.get("call", "call")?.data;
  if (data.state === "incoming") {
    Live.upsert("call", "call", data, t, 60_000);
    if (old?.state !== "incoming") {
      host?.banner("call", 45_000);
      Sound.play("question");
    }
  } else if (data.state === "active") {
    Live.upsert("call", "call", { ...data, name: data.name || old?.name || "Call", since: t }, t, 4 * 3600_000);
  } else if (data.state === "missed") {
    Live.upsert("call", "call", { ...data, name: data.name || old?.name || "Unknown caller" }, t, 8000);
    host?.banner("call", 5000);
  } else {
    Live.remove("call");
  }
}

// ── Timers, stopwatch, memo ───────────────────────────────────────────────────

let timerSeq = 0;

function startTimer(seconds: number, label = ""): string {
  const t = now();
  const id = `timer:${t.toString(36)}${timerSeq++}`;
  Live.upsert(id, "timer", { label: label.trim() || "Timer", duration: seconds, endsAt: t + seconds * 1000, pausedLeft: null, done: false }, t);
  Live.focusId = id;
  save();
  return id;
}

function toggleTimer(id: string) {
  if (id === TOOLS_TIMER) {
    Tools.timerToggle();
    mirrorTools();
    return;
  }
  const a = Live.get(id, "timer");
  if (!a || a.data.done) return;
  const t = now();
  const data: TimerData = a.data.pausedLeft == null
    ? { ...a.data, pausedLeft: timerLeft(a.data, t) }
    : { ...a.data, endsAt: t + a.data.pausedLeft * 1000, pausedLeft: null };
  Live.patch(id, "timer", data, t);
  save();
}

function restartTimer(id: string) {
  if (id === TOOLS_TIMER) {
    Tools.stopRinging();
    Tools.timerToggle();
    mirrorTools();
    return;
  }
  const a = Live.get(id, "timer");
  if (!a) return;
  const t = now();
  Live.upsert(id, "timer", { ...a.data, endsAt: t + a.data.duration * 1000, pausedLeft: null, done: false }, t);
  save();
}

function addToTimer(id: string, seconds: number) {
  if (id === TOOLS_TIMER) {
    Tools.timerAdd(seconds / 60);
    mirrorTools();
    return;
  }
  const a = Live.get(id, "timer");
  if (!a || a.data.done) return;
  const t = now();
  if (a.data.pausedLeft != null) Live.patch(id, "timer", { pausedLeft: a.data.pausedLeft + seconds, duration: a.data.duration + seconds }, t);
  else Live.patch(id, "timer", { endsAt: a.data.endsAt + seconds * 1000, duration: a.data.duration + seconds }, t);
  save();
}

/** There is one stopwatch, the Time page's (core/tools.ts): this drives it, and `mirrorTools` shows it. */
function stopwatch(action: "start" | "toggle" | "lap" | "reset") {
  const running = Tools.stopwatchRunning;
  if (action === "start") {
    if (!running) Tools.stopwatchToggle();
    Live.focusId = "stopwatch";
  } else if (action === "toggle") {
    Tools.stopwatchToggle();
  } else if (action === "lap") {
    if (running) Tools.stopwatchLapOrReset();
  } else {
    if (running) Tools.stopwatchToggle();
    Tools.stopwatchLapOrReset();
  }
  mirrorTools();
}

const TOOLS_TIMER = "tools:timer";

/**
 * The Time page's own timer, alarms and stopwatch, shown as live activities
 * like the rest: they keep running in core/tools.ts, the pill and the cards
 * only follow them.
 */
function mirrorTools() {
  const t = now();
  const live = Tools.live(t);
  const ring = Tools.ringing;
  const old = Live.get(TOOLS_TIMER, "timer")?.data;
  let next: TimerData | null = null;
  if (ring) next = { label: ring.kind === "alarm" ? `Alarm ${ring.label}` : "Timer", duration: 1, endsAt: 0, pausedLeft: null, done: true };
  else if (live?.kind === "timer") next = { label: "Timer", duration: Tools.timerDuration / 1000, endsAt: live.endAt, pausedLeft: null, done: false };
  else if (live?.kind === "timerPaused") next = { label: "Timer", duration: Tools.timerDuration / 1000, endsAt: 0, pausedLeft: live.left / 1000, done: false };
  if (!next) Live.remove(TOOLS_TIMER);
  else if (JSON.stringify(old) !== JSON.stringify(next)) Live.upsert(TOOLS_TIMER, "timer", next, t);

  const sw = Live.get("stopwatch", "stopwatch")?.data;
  if (!Tools.stopwatchRunning) {
    if (sw) Live.remove("stopwatch");
  } else {
    const since = t - Tools.stopwatchMs(t);
    const laps = Tools.laps;
    if (!sw || Math.abs((sw.since ?? 0) - since) > 80 || sw.laps.length !== laps.length) {
      Live.upsert("stopwatch", "stopwatch", { base: 0, since, laps: [...laps].reverse() }, t);
    }
  }
}

async function memoStart() {
  if (Live.ofKind("memo").some((m) => m.data.state === "recording")) return;
  const t = now();
  const res = await call<{ path?: string; error?: string }>("live_action", { action: "memo-start" });
  if (!res?.path) {
    lastError = res?.error ?? "Recording needs Clove Notch running as an app.";
    State.notify();
    return;
  }
  Live.upsert("memo", "memo", { path: res.path, state: "recording", since: t, seconds: 0, levels: [] }, t);
  Live.focusId = "memo";
  Sound.play("pop");
}

async function memoStop() {
  await call("live_action", { action: "memo-stop" });
}

function applyMemo(e: { level?: number; saved?: { path: string; seconds: number } }) {
  const a = Live.get("memo", "memo");
  if (!a) return;
  const t = now();
  if (e.saved) {
    Live.upsert("memo", "memo", { ...a.data, state: "saved", seconds: e.saved.seconds, path: e.saved.path }, t, 20_000);
    Sound.play("finish");
  } else if (e.level != null && a.data.state === "recording") {
    Live.patch("memo", "memo", { levels: [...a.data.levels, e.level].slice(-40) }, t);
  }
}

/** Rings the timers that ran out. Runs whether Clove Notch is shown or not. */
function checkTimers() {
  const t = now();
  for (const a of Live.ofKind("timer")) {
    if (a.data.done || a.data.pausedLeft != null || a.data.endsAt > t) continue;
    Live.upsert(a.id, "timer", { ...a.data, done: true }, t, 60_000);
    Live.focusId = a.id;
    host?.banner(a.id, 20_000);
    Sound.play("finish");
    window.setTimeout(() => Live.get(a.id, "timer")?.data.done && Sound.play("finish"), 1200);
    save();
  }
}

// ── Stocks ────────────────────────────────────────────────────────────────────

async function refreshQuotes() {
  quotesAt = now();
  const wanted = prefs.watchlist;
  for (const a of Live.ofKind("stock")) if (!wanted.includes(a.data.symbol)) Live.remove(a.id);
  if (!wanted.length) return;
  // One call for every symbol's every candidate; the first that answers is it.
  const codes = wanted.flatMap((s) => Live.get(`stock:${s}`, "stock")?.data.code ?? quoteCandidates(s));
  const json = await fetchJson("quote", [...new Set(codes)].join("|")) as { FormattedQuoteResult?: { FormattedQuote?: Record<string, unknown>[] } } | null;
  const quotes = json?.FormattedQuoteResult?.FormattedQuote ?? [];
  const t = now();
  for (const symbol of wanted) {
    const id = `stock:${symbol}`;
    const old = Live.get(id, "stock")?.data;
    const candidates = old ? [old.code] : quoteCandidates(symbol);
    let found: Omit<StockData, "series"> | null = null;
    for (const code of candidates) {
      found = parseQuote(quotes.find((q) => String(q.symbol).toUpperCase() === code), symbol);
      if (found) break;
    }
    if (!found) continue;
    Live.upsert(id, "stock", { ...found, series: old?.series ?? [] }, t);
    void refreshBars(id, found.code);
  }
}

async function refreshBars(id: string, code: string) {
  const series = parseBars(await fetchJson("bars", code));
  if (series.length > 1) Live.patch(id, "stock", { series }, now());
}

async function watch(symbol: string): Promise<boolean> {
  const s = symbol.trim().toUpperCase();
  if (!s) return false;
  if (!prefs.watchlist.includes(s)) prefs.watchlist = [...prefs.watchlist, s].slice(-8);
  save();
  await refreshQuotes();
  const ok = Live.get(`stock:${s}`) != null;
  if (!ok) {
    prefs.watchlist = prefs.watchlist.filter((x) => x !== s);
    lastError = IS_TAURI ? `No quote found for ${s}.` : "Quotes need Clove Notch running as an app.";
    save();
  } else {
    Live.focusId = `stock:${s}`;
    lastError = "";
  }
  State.notify();
  return ok;
}

function unwatch(symbol: string) {
  prefs.watchlist = prefs.watchlist.filter((x) => x !== symbol);
  Live.remove(`stock:${symbol}`);
  save();
}

// ── Sports ────────────────────────────────────────────────────────────────────

async function refreshScores() {
  scoresAt = now();
  const json = await fetchJson("scores", prefs.sport);
  if (json) allMatches = parseScoreboard(json, prefs.sport);
  const t = now();
  const mine = followedMatches(allMatches, prefs.follows).filter((m) => !prefs.hidden.includes(m.eventId)).slice(0, 3);
  const keep = new Set(mine.map((m) => `sports:${m.eventId}`));
  for (const a of Live.ofKind("sports")) if (!keep.has(a.id)) Live.remove(a.id);
  for (const m of mine) {
    const id = `sports:${m.eventId}`;
    const old = Live.get(id, "sports")?.data;
    Live.upsert(id, "sports", m, t);
    // A score that moved in a live match is worth a look.
    if (old && m.state === "in" && (old.home.score !== m.home.score || old.away.score !== m.away.score) && scoreJump(old, m)) {
      host?.banner(id, 4500);
    }
  }
  State.notify();
}

/** A wicket or a goal, not every run: the count after the slash, or a whole number. */
function scoreJump(a: SportsData, b: SportsData): boolean {
  const events = (s: string) => {
    const last = s.split("&").pop() ?? "";
    const wickets = /\/(\d+)/.exec(last);
    return wickets ? Number(wickets[1]) : /^\d{1,2}$/.test(last.trim()) ? Number(last) : null;
  };
  return events(a.home.score) !== events(b.home.score) || events(a.away.score) !== events(b.away.score);
}

function follow(team: string) {
  const name = team.trim();
  if (!name) return;
  if (!prefs.follows.some((f) => f.toLowerCase() === name.toLowerCase())) prefs.follows = [...prefs.follows, name].slice(-10);
  save();
  void refreshScores();
}

function unfollow(team: string) {
  prefs.follows = prefs.follows.filter((f) => f !== team);
  save();
  void refreshScores();
}

function setSport(sport: string) {
  prefs.sport = sport;
  allMatches = [];
  save();
  void refreshScores();
}

// ── Navigation ────────────────────────────────────────────────────────────────

interface Place { name: string; lon: number; lat: number }

async function geocode(query: string): Promise<Place | null> {
  const coords = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/.exec(query);
  if (coords) return { name: query.trim(), lat: Number(coords[1]), lon: Number(coords[2]) };
  const hits = await fetchJson("geocode", query) as { lat: string; lon: string; name?: string; display_name?: string }[] | null;
  const hit = hits?.[0];
  if (!hit) return null;
  return { name: hit.name || (hit.display_name ?? query).split(",")[0], lon: Number(hit.lon), lat: Number(hit.lat) };
}

/** Where this computer roughly is: the saved start, else its network's city. */
async function whereAmI(): Promise<Place | null> {
  if (prefs.home) return prefs.home;
  const ip = await fetchJson("whereami") as { latitude?: number; longitude?: number; city?: string } | null;
  if (ip?.latitude == null || ip.longitude == null) return null;
  return { name: ip.city ?? "Here", lon: ip.longitude, lat: ip.latitude };
}

async function navigate(to: string, from = ""): Promise<boolean> {
  lastError = "";
  const dest = await geocode(to);
  const origin = from.trim() ? await geocode(from) : await whereAmI();
  if (!dest || !origin) {
    lastError = !IS_TAURI ? "Routes need Clove Notch running as an app." : !dest ? `Couldn't find “${to}”.` : "Couldn't tell where to start from: add “from …”.";
    State.notify();
    return false;
  }
  const fix = (n: number) => n.toFixed(5);
  const json = await fetchJson("route", `${fix(origin.lon)},${fix(origin.lat)};${fix(dest.lon)},${fix(dest.lat)}`);
  const route = parseRoute(json, origin.name, dest.name, now());
  if (!route) {
    lastError = `No road route to ${dest.name}.`;
    State.notify();
    return false;
  }
  Live.upsert("nav", "nav", route, now());
  Live.focusId = "nav";
  save();
  return true;
}

function navStep(delta: number) {
  const a = Live.get("nav", "nav");
  if (!a) return;
  const stepIndex = Math.max(0, Math.min(a.data.steps.length - 1, a.data.stepIndex + delta));
  Live.patch("nav", "nav", { stepIndex } as Partial<NavData>, now());
  save();
}

async function setHome(query: string): Promise<boolean> {
  const place = await geocode(query);
  if (place) {
    prefs.home = place;
    save();
  }
  return place != null;
}

// ── Voice ─────────────────────────────────────────────────────────────────────

function applyVoice(v: Partial<VoiceData> & { phase?: string }) {
  const t = now();
  const old = Live.get("voice", "voice")?.data;
  const asked: string = v.phase ?? "";
  if (!asked || asked === "idle") {
    // The answer stays readable for a moment after CLOVE stops talking.
    if (old?.reply) Live.expire("voice", t + 4000);
    else Live.remove("voice");
    return;
  }
  const phase = asked as VoiceData["phase"];
  // Only the level moved: no need to wake the whole page for a new card.
  const data: VoiceData = {
    phase,
    heard: v.heard ?? (phase === "listening" && old?.phase !== "listening" ? "" : old?.heard ?? ""),
    reply: v.reply ?? (phase === "listening" ? "" : old?.reply ?? ""),
    level: v.level ?? old?.level ?? 0,
  };
  // Talking to CLOVE stays in the pill (its bars and "Listening", "Thinking", "Speaking"): opening the whole card on
  // every command covered the screen each time. The card is a hover or a click away.
  Live.upsert("voice", "voice", data, t, 90_000);
}

/** Wakes the CLOVE assistant so it listens now, as saying its name does. */
async function listen() {
  // Asked to listen: a muted microphone would hear nothing, so it comes back on first.
  const muted = await call<boolean>("clove_mute", { action: "off" });
  if (muted === false) State.cloveMuted = false;
  const answer = await call<string>("clove_ctl", { command: "wake" });
  if (answer == null || answer.startsWith("error")) {
    lastError = "CLOVE isn't running: start it from the CLOVE window.";
    State.notify();
    return;
  }
  applyVoice({ phase: "listening", heard: "", reply: "" });
}

// ── Pushes (the socket: the assistant, scripts) ───────────────────────────────

type Push = Record<string, unknown> & { op?: string };
const s = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
const n = (v: unknown): number => (typeof v === "number" ? v : Number(v) || 0);

function applyPush(p: Push) {
  const t = now();
  switch (p.op) {
    case "timer": {
      const seconds = typeof p.seconds === "number" ? p.seconds : parseDuration(s(p.duration));
      if (seconds && seconds > 0) host?.banner(startTimer(seconds, s(p.label)), 3500);
      break;
    }
    case "timer-cancel":
      for (const a of Live.ofKind("timer")) {
        if (!p.label || a.data.label.toLowerCase().includes(s(p.label).toLowerCase())) Live.remove(a.id);
      }
      save();
      break;
    case "stopwatch":
      stopwatch((s(p.action) || "start") as "start");
      if (Live.get("stopwatch")) host?.banner("stopwatch", 3000);
      break;
    case "memo":
      void (s(p.action) === "stop" ? memoStop() : memoStart().then(() => Live.get("memo") && host?.banner("memo", 3000)));
      break;
    case "navigate":
      void navigate(s(p.to), s(p.from)).then((ok) => ok && host?.banner("nav", 8000));
      break;
    case "navigate-end":
      Live.remove("nav");
      save();
      break;
    case "stock":
      if (p.remove) unwatch(s(p.symbol).toUpperCase());
      else void watch(s(p.symbol)).then((ok) => ok && host?.banner(`stock:${s(p.symbol).trim().toUpperCase()}`, 6000));
      break;
    case "follow":
      if (s(p.sport)) prefs.sport = s(p.sport);
      if (p.remove) unfollow(s(p.team));
      else follow(s(p.team));
      break;
    case "voice":
      applyVoice(p as Partial<VoiceData>);
      break;
    case "auth":
      authBanner({ method: (s(p.method) || "face") as AuthData["method"], ok: p.ok == null ? null : p.ok === true, detail: s(p.detail) });
      break;
    case "payment":
      applyPayment({ amount: n(p.amount), currency: s(p.currency) || "INR", party: s(p.party), direction: p.direction === "received" ? "received" : "paid", app: s(p.app) });
      break;
    case "call":
      applyCall({ name: s(p.name) || "Unknown caller", number: s(p.number), app: s(p.app) || "Phone", state: (s(p.state) || "incoming") as CallData["state"], video: p.video === true, since: t });
      break;
    case "ride":
    case "delivery": {
      const brand = brandById(s(p.brand).toLowerCase());
      if (!brand) break;
      const id = `${brand.kind}:${brand.id}`;
      if (brand.kind === "ride") Live.upsert(id, "ride", { brand: brand.id, stage: n(p.stage), eta: s(p.eta), driver: s(p.driver), vehicle: s(p.vehicle), otp: s(p.otp), text: s(p.text) }, t);
      else Live.upsert(id, "delivery", { brand: brand.id, stage: n(p.stage), eta: s(p.eta), courier: s(p.courier), otp: s(p.otp), text: s(p.text) }, t);
      host?.banner(id, 5000);
      save();
      break;
    }
    case "notification":
      applyNotification({ id: 0, app: s(p.app), summary: s(p.summary), body: s(p.body) });
      break;
    case "media":
      void mediaControl(s(p.action) || "toggle");
      break;
    case "dismiss":
      Live.remove(s(p.id));
      save();
      break;
    case "show":
      host?.show(Live.all().find((a) => a.kind === s(p.kind) || a.id === s(p.id))?.id ?? null);
      break;
  }
  State.notify();
}

// ── Media control ─────────────────────────────────────────────────────────────

async function mediaControl(action: string, value?: number) {
  const a = Live.get("media", "media");
  if (!a) return;
  const t = now();
  // The card answers at once; the player's own report follows.
  if (action === "toggle") Live.patch("media", "media", { playing: !a.data.playing, position: currentPosition(a.data, t), positionAt: t }, t);
  if (action === "seek" && value != null) Live.patch("media", "media", { position: value, positionAt: t }, t);
  await call("live_media_control", { bus: a.data.bus, action, value: value ?? null });
}

function currentPosition(m: MediaData, t: number): number {
  return m.position + (m.playing ? Math.max(0, (t - m.positionAt) / 1000) : 0);
}

// ── The clock ─────────────────────────────────────────────────────────────────

/** Activities whose card moves by itself, second by second. */
function ticking(): boolean {
  return Live.all().some((a) =>
    (is(a, "timer") && !a.data.done && a.data.pausedLeft == null) ||
    (is(a, "stopwatch") && a.data.since != null) ||
    (is(a, "memo") && a.data.state === "recording") ||
    is(a, "recording") || (is(a, "media") && a.data.playing) ||
    (is(a, "call") && a.data.state === "active"));
}

function heartbeat() {
  checkTimers();
  mirrorTools();
  const pruned = Live.prune(now());
  if (pruned) save();
  if (State.mode !== "hidden" && ticking()) State.notify();
  const t = now();
  // Quotes every minute while one is on screen, scores every half minute while
  // a followed match is live — and both slowly otherwise, so they are fresh.
  const stockOpen = Live.ofKind("stock").some((a) => a.data.marketOpen);
  if (prefs.watchlist.length && t - quotesAt > (stockOpen ? 60_000 : 10 * 60_000)) void refreshQuotes();
  const liveMatch = Live.ofKind("sports").some((a) => a.data.state === "in");
  if (prefs.follows.length && t - scoresAt > (liveMatch ? 30_000 : 5 * 60_000)) void refreshScores();
}

// ── Public ────────────────────────────────────────────────────────────────────

export const LiveCtl = {
  get system() { return system; },
  get players() { return players; },
  get prefs() { return prefs; },
  get matches() { return allMatches; },
  get error() { return lastError; },
  clearError() { lastError = ""; },
  /** The cover of the track the media card shows, once it has arrived. */
  artFor(m: MediaData): string | null {
    return artwork && m.artUrl && artwork.artUrl === m.artUrl ? artwork.dataUrl : null;
  },
  mediaControl,
  pickPlayer(bus: string) {
    mediaBus = bus;
    applyPlayers(players);
  },
  startTimer, toggleTimer, restartTimer, addToTimer, stopwatch,
  memoStart, memoStop,
  watch, unwatch, refreshQuotes,
  follow, unfollow, setSport, refreshScores,
  navigate, navStep, setHome,
  /** The cross on a match: off the notch, and it stays off. */
  hideMatch(eventId: string) {
    if (!eventId) return;
    prefs.hidden = [...prefs.hidden.filter((x) => x !== eventId), eventId].slice(-40);
    Live.remove(`sports:${eventId}`);
    save();
  },
  listen,
  endNav() {
    Live.remove("nav");
    save();
  },
  dismiss(id: string) {
    if (id === TOOLS_TIMER) {
      if (Tools.ringing) Tools.stopRinging();
      else Tools.timerReset();
      mirrorTools();
      return;
    }
    Live.remove(id);
    save();
  },
  stopRecording(pid: number) {
    void call("live_action", { action: "stop-recording", arg: String(pid) });
  },
  hotspotOff() {
    void call("live_action", { action: "hotspot-off" });
  },
  reveal(path: string) {
    void call("live_action", { action: "reveal", arg: path });
  },
  playFile(path: string) {
    void call("live_action", { action: "play-file", arg: path });
  },
  /**
   * Opens what an activity is about: its page in the browser, the player's own
   * window, a memo's folder. True when there was something to open.
   */
  open(id: string): boolean {
    const a = Live.get(id);
    if (!a) return false;
    const url = linkOf(a);
    if (url) {
      void call("open_url", { url });
      return true;
    }
    if (is(a, "media")) {
      // No address: the player's window, raised (MPRIS) or found by its name (Hyprland).
      void call<boolean>("live_media_control", { bus: a.data.bus, action: "raise", value: null }).then((ok) => {
        if (!ok) void call("live_action", { action: "focus-app", arg: a.data.app });
      });
      return true;
    }
    if (is(a, "call")) {
      void call("live_action", { action: "focus-app", arg: a.data.app });
      return true;
    }
    if (is(a, "memo") && a.data.state === "saved") {
      void call("live_action", { action: "reveal", arg: a.data.path });
      return true;
    }
    return false;
  },
  /** "Accept": the call is answered in its app, brought to the front. */
  acceptCall() {
    const a = Live.get("call", "call");
    if (!a) return;
    void call("live_action", { action: "focus-app", arg: a.data.app });
    Live.upsert("call", "call", { ...a.data, state: "active", since: now() }, now(), 4 * 3600_000);
  },
  endCall() {
    Live.remove("call");
  },
  mirrorTools,
  push: applyPush,
  notification: applyNotification,
  system_: applySystem,
  players_: applyPlayers,
};

export function registerLiveHandlers(h: LiveHost) {
  host = h;
  Live.onChange = () => State.notify();
  load();
  window.setInterval(heartbeat, 500);

  void onEvent<Player[]>("live-media", applyPlayers);
  void onEvent<{ artUrl: string; dataUrl: string }>("live-art", (art) => {
    artwork = art;
    State.notify();
  });
  void onEvent<SystemSnapshot>("live-system", applySystem);
  void onEvent<DesktopNotification>("live-notification", applyNotification);
  void onEvent<{ event: string; number: string; name: string; device: string }>("live-call", (c) => {
    const state = c.event === "ringing" ? "incoming" : c.event === "talking" ? "active" : c.event === "missedCall" ? "missed" : "ended";
    applyCall({ name: c.name || c.number || "Unknown caller", number: c.number, app: "Phone", state, video: false, since: now(), device: c.device });
  });
  void onEvent<AuthData>("live-auth", authBanner);
  void onEvent<{ level?: number; saved?: { path: string; seconds: number } }>("live-memo", applyMemo);
  void onEvent<Push>("live-push", applyPush);

  // What is already true when the page loads. Asked twice: the first answer can
  // come before the watchers have had their first look.
  const first = () => void call<{ media: Player[]; system: SystemSnapshot | null }>("live_start").then((now_) => {
    if (!now_) return;
    if (now_.media?.length || players.length) applyPlayers(now_.media ?? []);
    if (now_.system && !system) applySystem(now_.system);
  });
  first();
  window.setTimeout(first, 2500);
  if (prefs.watchlist.length) void refreshQuotes();
  if (prefs.follows.length) void refreshScores();
}

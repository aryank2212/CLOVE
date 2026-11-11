// Live Activities: what Clove Notch shows around and inside the pill while
// something is going on — music, a call, a timer, a ride, a match, a stock.
// This file is the pure part: the store, the order they are shown in, and the
// parsers that turn a desktop notification, a quote, a scoreboard or a route
// into an activity. No DOM, no Tauri (src/island/live.ts feeds it).

export type LiveKind =
  | "call" | "voice" | "auth" | "payment" | "timer" | "stopwatch" | "memo" | "recording"
  | "nav" | "ride" | "delivery" | "media" | "sports" | "stock" | "device" | "battery"
  | "hotspot" | "camera";

export type MediaSource = "spotify" | "youtube" | "ytmusic" | "applemusic" | "browser" | "video" | "music";

export interface MediaData {
  bus: string;
  app: string;
  source: MediaSource;
  title: string;
  artist: string;
  album: string;
  artUrl: string | null;
  /** Seconds; 0 when the player doesn't say (a live stream). */
  duration: number;
  /** Seconds at `positionAt` (Unix ms); runs on from there while playing. */
  position: number;
  positionAt: number;
  playing: boolean;
  canNext: boolean;
  canPrev: boolean;
  canSeek: boolean;
  /** The page or track it plays, when the player says (a browser tab's address). */
  url?: string;
}

export interface CallData {
  name: string;
  number: string;
  app: string;
  state: "incoming" | "active" | "missed" | "ended";
  video: boolean;
  /** Unix ms the current state began. */
  since: number;
  notificationId?: number;
  /** KDE Connect device the call rings on, when it is a phone call. */
  device?: string;
}

export interface TimerData {
  label: string;
  /** Seconds the timer was set for. */
  duration: number;
  /** Unix ms it rings at; ignored while paused. */
  endsAt: number;
  /** Seconds left while paused, else null. */
  pausedLeft: number | null;
  done: boolean;
}

export interface StopwatchData {
  /** Ms counted before the current run. */
  base: number;
  /** Unix ms the current run began, null while stopped. */
  since: number | null;
  laps: number[];
}

export interface MemoData {
  path: string;
  state: "recording" | "saved";
  since: number;
  /** Seconds, once saved. */
  seconds: number;
  /** Recent input levels 0…1, newest last. */
  levels: number[];
}

export interface RecordingData { app: string; pid: number; since: number }

export interface NavStep { text: string; distance: number; modifier: string }

export interface NavData {
  destination: string;
  origin: string;
  steps: NavStep[];
  stepIndex: number;
  /** Metres and seconds for the whole route. */
  distance: number;
  duration: number;
  /** Unix ms of arrival if leaving at `startedAt`. */
  etaAt: number;
  /** The route as [lon, lat], thinned for the mini map. */
  line: [number, number][];
  source: "route" | "phone";
}

export interface RideData {
  brand: string;
  /** 0 finding · 1 driver on the way · 2 arrived · 3 on trip · 4 done. */
  stage: number;
  eta: string;
  driver: string;
  vehicle: string;
  otp: string;
  text: string;
}

export interface DeliveryData {
  brand: string;
  /** 0 confirmed · 1 packed / shipped · 2 out for delivery · 3 delivered. */
  stage: number;
  eta: string;
  courier: string;
  otp: string;
  text: string;
}

export interface TeamScore { abbr: string; name: string; score: string; logo: string; winner: boolean }

export interface SportsData {
  eventId: string;
  sport: string;
  league: string;
  state: "pre" | "in" | "post";
  status: string;
  summary: string;
  startsAt: number;
  /** The match's page. */
  link: string;
  home: TeamScore;
  away: TeamScore;
}

export interface StockData {
  symbol: string;
  /** What the quote service calls it (RELIANCE-IN, .NSEI, BTC.CM=). */
  code: string;
  name: string;
  price: number;
  change: number;
  changePct: number;
  currency: string;
  series: number[];
  prevClose: number;
  marketOpen: boolean;
}

export interface AuthData {
  method: "face" | "fingerprint" | "password" | "unlock" | "lock";
  /** null while it is still checking. */
  ok: boolean | null;
  detail: string;
}

export interface PaymentData {
  amount: number;
  currency: string;
  party: string;
  direction: "paid" | "received";
  app: string;
}

export interface DeviceData {
  name: string;
  type: "headphones" | "phone" | "mouse" | "keyboard" | "other";
  percent: number | null;
  charging: boolean;
}

export interface BatteryData { percent: number; charging: boolean; event: "low" | "charging" | "full" | "unplugged" }
export interface HotspotData { ssid: string; iface: string; clients: number }
export interface CameraData { apps: string[] }
export interface VoiceData { phase: "listening" | "thinking" | "working" | "speaking"; heard: string; reply: string; level: number }

export interface LiveDataMap {
  call: CallData; voice: VoiceData; auth: AuthData; payment: PaymentData; timer: TimerData;
  stopwatch: StopwatchData; memo: MemoData; recording: RecordingData; nav: NavData; ride: RideData;
  delivery: DeliveryData; media: MediaData; sports: SportsData; stock: StockData; device: DeviceData;
  battery: BatteryData; hotspot: HotspotData; camera: CameraData;
}

export interface LiveActivity<K extends LiveKind = LiveKind> {
  id: string;
  kind: K;
  data: LiveDataMap[K];
  startedAt: number;
  updatedAt: number;
  /** Unix ms after which it leaves by itself (a banner, a finished delivery). */
  expiresAt?: number;
}

export type AnyActivity = { [K in LiveKind]: LiveActivity<K> }[LiveKind];

/** Typed access to an activity's data once its kind is known. */
export function is<K extends LiveKind>(a: LiveActivity | null | undefined, kind: K): a is LiveActivity<K> {
  return a?.kind === kind;
}

// ── Order ─────────────────────────────────────────────────────────────────────

const BASE_PRIORITY: Record<LiveKind, number> = {
  call: 100, voice: 96, auth: 92, payment: 90, device: 86, battery: 84, memo: 76, recording: 74,
  nav: 72, timer: 70, ride: 68, delivery: 60, stopwatch: 56, media: 50, sports: 44, hotspot: 24,
  camera: 22, stock: 20,
};

/** How much an activity wants the pill, right now. */
export function priority(a: LiveActivity, now: number): number {
  let p = BASE_PRIORITY[a.kind];
  if (is(a, "timer")) {
    if (a.data.done) p = 98;
    else if (a.data.pausedLeft == null && a.data.endsAt - now < 60_000) p = 80;
  }
  if (is(a, "call") && a.data.state !== "incoming") p = a.data.state === "active" ? 94 : 40;
  if (is(a, "media") && !a.data.playing) p = 18;
  if (is(a, "sports") && a.data.state !== "in") p = 16;
  if (is(a, "delivery") && a.data.stage >= 3) p = 30;
  if (is(a, "ride") && a.data.stage >= 4) p = 30;
  if (is(a, "memo") && a.data.state === "saved") p = 30;
  if (is(a, "stopwatch") && a.data.since == null) p = 26;
  return p;
}

export class LiveStore {
  private items = new Map<string, LiveActivity>();
  /** The activity the expanded card shows; null follows the most important one. */
  focusId: string | null = null;
  onChange: (() => void) | null = null;

  get size(): number {
    return this.items.size;
  }

  get<K extends LiveKind>(id: string, kind?: K): LiveActivity<K> | null {
    const a = this.items.get(id);
    return a && (!kind || a.kind === kind) ? (a as LiveActivity<K>) : null;
  }

  all(): LiveActivity[] {
    return [...this.items.values()];
  }

  ofKind<K extends LiveKind>(kind: K): LiveActivity<K>[] {
    return this.all().filter((a): a is LiveActivity<K> => a.kind === kind);
  }

  /** Adds or replaces; `startedAt` survives a replace. True when it is new. */
  upsert<K extends LiveKind>(id: string, kind: K, data: LiveDataMap[K], now: number, ttlMs?: number): boolean {
    const old = this.items.get(id);
    const fresh = !old || old.kind !== kind;
    this.items.set(id, {
      id, kind, data,
      startedAt: fresh ? now : old.startedAt,
      updatedAt: now,
      expiresAt: ttlMs != null ? now + ttlMs : undefined,
    });
    this.onChange?.();
    return fresh;
  }

  patch<K extends LiveKind>(id: string, kind: K, data: Partial<LiveDataMap[K]>, now: number): boolean {
    const a = this.get(id, kind);
    if (!a) return false;
    a.data = { ...a.data, ...data };
    a.updatedAt = now;
    this.onChange?.();
    return true;
  }

  expire(id: string, at: number) {
    const a = this.items.get(id);
    if (a) a.expiresAt = at;
  }

  remove(id: string): boolean {
    const had = this.items.delete(id);
    if (had) {
      if (this.focusId === id) this.focusId = null;
      this.onChange?.();
    }
    return had;
  }

  /** Drops what has run out. True when something left. */
  prune(now: number): boolean {
    let gone = false;
    for (const a of this.items.values()) {
      if (a.expiresAt != null && a.expiresAt <= now) {
        this.items.delete(a.id);
        if (this.focusId === a.id) this.focusId = null;
        gone = true;
      }
    }
    if (gone) this.onChange?.();
    return gone;
  }

  /** Most important first; a tie goes to the one that changed last. */
  ranked(now: number): LiveActivity[] {
    return this.all().sort((a, b) => priority(b, now) - priority(a, now) || b.updatedAt - a.updatedAt);
  }

  /** What the compact pill shows. */
  primary(now: number): LiveActivity | null {
    return this.ranked(now)[0] ?? null;
  }

  /** What the small bubble next to the pill shows. */
  secondary(now: number): LiveActivity | null {
    return this.ranked(now)[1] ?? null;
  }

  /** What the expanded card shows. */
  focused(now: number): LiveActivity | null {
    return (this.focusId ? this.items.get(this.focusId) : null) ?? this.primary(now);
  }

  clear() {
    this.items.clear();
    this.focusId = null;
    this.onChange?.();
  }
}

// ── Words and numbers ─────────────────────────────────────────────────────────

/** m:ss, or h:mm:ss past an hour. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const pad = (n: number) => String(n).padStart(2, "0");
  return s >= 3600
    ? `${Math.floor(s / 3600)}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
    : `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

/** "5 min", "1 h 20" — the short way a duration is said in the pill. */
export function shortDuration(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 60) return `${m} min`;
  const rest = m % 60;
  return rest ? `${Math.floor(m / 60)} h ${rest}` : `${Math.floor(m / 60)} h`;
}

export function fmtDistance(metres: number): string {
  if (metres < 950) return `${Math.max(10, Math.round(metres / 10) * 10)} m`;
  const km = metres / 1000;
  return `${km < 10 ? km.toFixed(1) : Math.round(km)} km`;
}

const CURRENCY_SIGN: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£", JPY: "¥" };

export function fmtMoney(amount: number, currency: string): string {
  const sign = CURRENCY_SIGN[currency.toUpperCase()] ?? `${currency} `;
  const digits = Math.abs(amount) >= 1000 || Number.isInteger(amount) ? (Number.isInteger(amount) ? 0 : 2) : 2;
  return `${sign}${amount.toLocaleString(currency.toUpperCase() === "INR" ? "en-IN" : "en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: 2,
  })}`;
}

/**
 * A duration as someone types or says it: "5m", "1h 30m", "90s", "2:30",
 * "10 minutes", "an hour", or a bare number of minutes. Seconds, or null.
 */
export function parseDuration(raw: string): number | null {
  const text = raw.trim().toLowerCase().replace(/\ban?\b/g, "1").replace(/half an? hour/g, "30 min");
  if (!text) return null;
  const colon = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (colon) {
    const [a, b, c] = [Number(colon[1]), Number(colon[2]), colon[3] != null ? Number(colon[3]) : null];
    return c != null ? a * 3600 + b * 60 + c : a * 60 + b;
  }
  if (/^\d+(\.\d+)?$/.test(text)) return Math.round(Number(text) * 60);
  let total = 0;
  let found = false;
  for (const m of text.matchAll(/(\d+(?:\.\d+)?)\s*(h(?:ou)?rs?|h|m(?:in(?:ute)?s?)?|s(?:ec(?:ond)?s?)?)\b/g)) {
    const n = Number(m[1]);
    total += m[2].startsWith("h") ? n * 3600 : m[2].startsWith("m") ? n * 60 : n;
    found = true;
  }
  return found && total > 0 ? Math.round(total) : null;
}

/** Seconds left on a timer at `now`. */
export function timerLeft(t: TimerData, now: number): number {
  if (t.done) return 0;
  return t.pausedLeft ?? Math.max(0, (t.endsAt - now) / 1000);
}

export function stopwatchMs(s: StopwatchData, now: number): number {
  return s.base + (s.since != null ? now - s.since : 0);
}

/** Where the player is at `now`, capped at the end. */
export function mediaPosition(m: MediaData, now: number): number {
  const p = m.position + (m.playing ? Math.max(0, (now - m.positionAt) / 1000) : 0);
  return m.duration > 0 ? Math.min(p, m.duration) : p;
}

// ── Brands (rides and deliveries) ─────────────────────────────────────────────

export interface Brand {
  id: string;
  name: string;
  kind: "ride" | "delivery";
  match: RegExp;
  /** Tile colour and the colour of the letter on it. */
  color: string;
  ink: string;
}

// Order matters: "Uber Eats" and "Swiggy Instamart" before "Uber" and "Swiggy".
export const BRANDS: Brand[] = [
  { id: "ubereats", name: "Uber Eats", kind: "delivery", match: /\buber\s*eats\b/i, color: "#06C167", ink: "#000" },
  { id: "uber", name: "Uber", kind: "ride", match: /\buber\b/i, color: "#FFFFFF", ink: "#000" },
  { id: "ola", name: "Ola", kind: "ride", match: /\bola\b(?!\s*electric)/i, color: "#C8E639", ink: "#111" },
  { id: "rapido", name: "Rapido", kind: "ride", match: /\brapido\b/i, color: "#F9C935", ink: "#111" },
  { id: "blinkit", name: "Blinkit", kind: "delivery", match: /\bblinkit\b/i, color: "#F8CB46", ink: "#1C1C1C" },
  { id: "instamart", name: "Instamart", kind: "delivery", match: /\binstamart\b/i, color: "#FC8019", ink: "#fff" },
  { id: "zepto", name: "Zepto", kind: "delivery", match: /\bzepto\b/i, color: "#8B2FF5", ink: "#fff" },
  { id: "swiggy", name: "Swiggy", kind: "delivery", match: /\bswiggy\b/i, color: "#FC8019", ink: "#fff" },
  { id: "zomato", name: "Zomato", kind: "delivery", match: /\bzomato\b/i, color: "#E23744", ink: "#fff" },
  { id: "amazon", name: "Amazon", kind: "delivery", match: /\bamazon\b/i, color: "#FF9900", ink: "#111" },
  { id: "flipkart", name: "Flipkart", kind: "delivery", match: /\bflipkart\b/i, color: "#2874F0", ink: "#FFE500" },
  { id: "bigbasket", name: "BigBasket", kind: "delivery", match: /\bbig\s?basket\b/i, color: "#84C225", ink: "#111" },
  { id: "myntra", name: "Myntra", kind: "delivery", match: /\bmyntra\b/i, color: "#FF3F6C", ink: "#fff" },
];

/** Where each service shows the ride or the order itself. */
const BRAND_PAGES: Record<string, string> = {
  ubereats: "https://www.ubereats.com/orders",
  uber: "https://riders.uber.com/trips",
  ola: "https://book.olacabs.com/",
  rapido: "https://www.rapido.bike/",
  blinkit: "https://blinkit.com/account/orders",
  instamart: "https://www.swiggy.com/my-account/orders",
  zepto: "https://www.zeptonow.com/account/orders",
  swiggy: "https://www.swiggy.com/my-account/orders",
  zomato: "https://www.zomato.com/",
  amazon: "https://www.amazon.in/gp/css/order-history",
  flipkart: "https://www.flipkart.com/account/orders",
  bigbasket: "https://www.bigbasket.com/order/list/",
  myntra: "https://www.myntra.com/my/orders",
};

/** The web page behind an activity, opened by a click on its card; null when it has none. */
export function linkOf(a: LiveActivity): string | null {
  if (is(a, "media")) return a.data.url && /^https?:\/\//.test(a.data.url) ? a.data.url : null;
  if (is(a, "stock")) return `https://www.cnbc.com/quotes/${encodeURIComponent(a.data.code)}`;
  if (is(a, "sports")) return /^https:\/\//.test(a.data.link) ? a.data.link : `https://www.espn.in/${a.data.sport === "soccer" ? "football" : a.data.sport}/`;
  if (is(a, "ride") || is(a, "delivery")) return BRAND_PAGES[a.data.brand] ?? null;
  if (is(a, "nav") && a.data.source === "route") {
    const q = (s: string) => encodeURIComponent(s);
    return `https://www.google.com/maps/dir/?api=1&origin=${q(a.data.origin)}&destination=${q(a.data.destination)}&travelmode=driving`;
  }
  return null;
}

export function brandById(id: string): Brand | undefined {
  return BRANDS.find((b) => b.id === id);
}

export const RIDE_STAGES = ["Finding a driver", "Driver on the way", "Driver has arrived", "On trip", "Trip completed"];
export const DELIVERY_STAGES = ["Order confirmed", "Packed", "Out for delivery", "Delivered"];

const RIDE_RULES: [number, RegExp][] = [
  [4, /trip (has |is )?(ended|completed|finished)|ride (has |is )?(ended|completed)|you('ve| have) (arrived|reached)|thanks for riding|rate your (ride|trip|driver|captain)|hope you enjoyed/i],
  [3, /(trip|ride) (has |is )?started|on (the|your) way to (your )?(destination|drop)|enjoy (your|the) ride|heading to|you('re| are) on (the|your) way/i],
  [2, /(driver|captain|cab|auto|ride|bike|car|pilot) (has |is )?(arrived|here|waiting|reached)|has arrived|is waiting (for you|outside)|arrived at (your )?pickup/i],
  [1, /is arriving|arriving in|arrives in|on (the|his|her|their) way|driver (is )?assigned|captain (is )?assigned|accepted your|(ride|booking|trip) (is )?confirmed|\d+\s*min(ute)?s? away|is nearby|will reach|reaching in|picking you up/i],
  [0, /finding|looking for|searching for|connecting you|requesting|booking your/i],
];

const DELIVERY_RULES: [number, RegExp][] = [
  [3, /\b(was |been |is )?delivered\b|order (is )?complete|handed over|enjoy your (order|meal|food)|left at (your|the) door/i],
  [2, /out for delivery|on (the|its|their|his|her) way|picked up|is nearby|reached your (location|doorstep|gate)|delivery (partner|executive|valet|agent) (is )?(assigned|on)|at your doorstep/i],
  [1, /\bpack(ed|ing)\b|being (packed|prepared)|preparing|\bshipped\b|dispatched|in transit|has left|ready for (pickup|dispatch)/i],
  // Said of a packed parcel as much as of one on the road: only when nothing above says which.
  [2, /is arriving|arriving (in|today|soon|by)|arrives? in|\d+\s*min(ute)?s? away|will (reach|arrive)/i],
  [0, /order (has been |is |was )?(placed|confirmed|received|accepted)|order confirmation|thank(s| you) for (your )?(order|shopping)|we('ve| have) (got|received) your order/i],
];

const CANCELLED = /\bcancel(l)?ed\b|\brefund(ed)?\b.*order|could(n't| not) (find|deliver)/i;

function stageOf(rules: [number, RegExp][], text: string): number | null {
  for (const [stage, re] of rules) if (re.test(text)) return stage;
  return null;
}

/** "8 min", "2:15 pm", "tomorrow", "12 Nov" — when it gets here, as the message says it. */
export function findEta(text: string): string {
  const mins = /(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*min(?:ute)?s?\b/i.exec(text);
  if (mins) return `${mins[2] ?? mins[1]} min`;
  const by = /\b(?:by|at|around|before)\s+(\d{1,2}[:.]\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))/i.exec(text);
  if (by) return by[1].replace(".", ":").replace(/\s+/g, " ").toLowerCase();
  const day = /\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.exec(text);
  if (day) return day[1][0].toUpperCase() + day[1].slice(1).toLowerCase();
  const date = /\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b/i.exec(text);
  return date ? date[1] : "";
}

export function findOtp(text: string): string {
  return /\b(?:otp|pin|code)\b\D{0,14}(\d{4,6})\b/i.exec(text)?.[1] ?? /\b(\d{4,6})\s+is (?:your|the) (?:otp|pin|code)\b/i.exec(text)?.[1] ?? "";
}

const NOT_A_NAME = new Set(["is", "has", "will", "assigned", "arriving", "on", "the", "your", "details", "partner"]);

export function findPerson(text: string): string {
  const m = /\b(?:driver|captain|partner|rider|valet|executive|agent|pilot)[,:]?\s+([A-Z][a-z]{1,15}(?:\s[A-Z][a-z]{1,15})?)\b/.exec(text) ??
    /\b([A-Z][a-z]{1,15}(?:\s[A-Z][a-z]{1,15})?)\s+(?:is (?:your|on|arriving|picking|bringing|delivering)|has (?:arrived|picked)|will (?:deliver|pick))/.exec(text);
  const name = m?.[1] ?? "";
  return NOT_A_NAME.has(name.split(" ")[0].toLowerCase()) ? "" : name;
}

export function findPlate(text: string): string {
  return /\b([A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{3,4})\b/.exec(text)?.[1] ?? "";
}

// ── Notifications → activities ───────────────────────────────────────────────

export interface DesktopNotification {
  id: number;
  app: string;
  summary: string;
  body: string;
}

export type Classified =
  | { kind: "ride"; id: string; data: RideData }
  | { kind: "delivery"; id: string; data: DeliveryData }
  | { kind: "payment"; id: string; data: PaymentData }
  | { kind: "call"; id: string; data: CallData }
  | { kind: "nav"; id: string; instruction: string; eta: string }
  | { kind: "cancel"; id: string };

const CALL_APPS = /whatsapp|telegram|signal|discord|teams|zoom|meet|skype|slack|facetime|phone|dialer|kde ?connect|duo|viber|messenger/i;
const INCOMING = /incoming (voice |video |audio |group )?call|is calling|calling you|\bringing\b|wants to (video )?(call|facetime)|started a (video |voice )?call/i;
const MISSED = /missed (voice |video |audio )?call/i;

const strip = (s: string) => s.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();

function callerOf(n: DesktopNotification): string {
  const clean = (s: string) => s.replace(INCOMING, "").replace(MISSED, "").replace(/\b(from|voice|video|audio|call)\b/gi, "").replace(/[:\-–—…]+/g, " ").replace(/\s+/g, " ").trim();
  const fromSummary = clean(n.summary);
  // "WhatsApp" as a summary is the app, not the caller.
  if (fromSummary && !CALL_APPS.test(fromSummary)) return fromSummary;
  return clean(n.body) || "Unknown caller";
}

const PAY_OUT = /\b(paid|debited|sent|spent|payment (of|successful|done|completed|received by)|purchase|transaction (of|successful)|withdrawn|charged)\b/i;
const PAY_IN = /\b(received|credited|refund(ed)?|deposited|cashback)\b/i;
const AMOUNT = /(₹|rs\.?|inr|\$|usd|€|eur|£|gbp)\s?([\d,]+(?:\.\d{1,2})?)/i;
const PAY_NOISE = /\b(offer|off on|win|sale|coupon|discount|upto|up to|due|bill is|recharge now|pay now|request(ed)? (money|payment)|reminder|otp)\b/i;

function currencyOf(sign: string): string {
  const s = sign.toLowerCase().replace(".", "");
  if (s === "₹" || s === "rs" || s === "inr") return "INR";
  if (s === "$" || s === "usd") return "USD";
  if (s === "€" || s === "eur") return "EUR";
  return "GBP";
}

function partyOf(text: string, direction: "paid" | "received"): string {
  const prep = direction === "paid" ? "(?:to|at|for)" : "(?:from|by)";
  const m = new RegExp(`\\b${prep}\\s+((?:[A-Z0-9][\\w&.'@-]*)(?:\\s+[A-Z0-9][\\w&.'@-]*){0,3})`).exec(text);
  const name = (m?.[1] ?? "").replace(/[.,]+$/, "");
  return /^(your|a\/c|ac|account|upi|vpa|rs|inr)\b/i.test(name) ? "" : name;
}

/**
 * What a desktop notification means to Clove Notch, if anything. Phone
 * notifications mirrored by KDE Connect arrive the same way, so a ride booked
 * or an order placed on the phone is followed here.
 */
export function classifyNotification(n: DesktopNotification, now: number): Classified | null {
  const summary = strip(n.summary);
  const body = strip(n.body);
  const text = `${summary}. ${body}`;
  const all = `${n.app} ${text}`;

  if (MISSED.test(text)) {
    return { kind: "call", id: "call", data: { name: callerOf({ ...n, summary, body }), number: "", app: n.app, state: "missed", video: /video/i.test(text), since: now, notificationId: n.id } };
  }
  if (INCOMING.test(text) && (CALL_APPS.test(all) || /call/i.test(summary))) {
    return {
      kind: "call", id: "call",
      data: { name: callerOf({ ...n, summary, body }), number: "", app: n.app, state: "incoming", video: /video|facetime|\bmeet\b/i.test(all), since: now, notificationId: n.id },
    };
  }

  const brand = BRANDS.find((b) => b.match.test(all));
  if (brand) {
    const id = `${brand.kind}:${brand.id}`;
    if (CANCELLED.test(text)) return { kind: "cancel", id };
    if (brand.kind === "ride") {
      const stage = stageOf(RIDE_RULES, text);
      if (stage != null) {
        return { kind: "ride", id, data: { brand: brand.id, stage, eta: stage < 4 ? findEta(text) : "", driver: findPerson(text), vehicle: findPlate(text), otp: findOtp(text), text: body || summary } };
      }
    } else {
      const stage = stageOf(DELIVERY_RULES, text);
      if (stage != null) {
        return { kind: "delivery", id, data: { brand: brand.id, stage, eta: stage < 3 ? findEta(text) : "", courier: findPerson(text), otp: findOtp(text), text: body || summary } };
      }
    }
  }

  const amount = AMOUNT.exec(text);
  if (amount && !PAY_NOISE.test(text)) {
    const direction = PAY_IN.test(text) && !/\bdebited\b/i.test(text) ? "received" : PAY_OUT.test(text) ? "paid" : null;
    const value = Number(amount[2].replace(/,/g, ""));
    if (direction && value > 0) {
      return { kind: "payment", id: "payment", data: { amount: value, currency: currencyOf(amount[1]), party: partyOf(text, direction), direction, app: n.app } };
    }
  }

  if (/\bmaps\b|waze|navigation/i.test(n.app) && /\b(turn|head|continue|keep|exit|merge|roundabout|arrive|destination|u-turn)\b/i.test(text)) {
    return { kind: "nav", id: "nav", instruction: body || summary, eta: findEta(summary) || findEta(body) };
  }
  return null;
}

/** A newer message about a ride or an order never moves it backwards. */
export function mergeStage<T extends RideData | DeliveryData>(old: T | undefined, next: T): T {
  if (!old) return next;
  const keep = <K extends keyof T>(k: K) => (next[k] || old[k]) as T[K];
  const merged = { ...next, otp: keep("otp" as keyof T), eta: next.eta || (next.stage === old.stage ? old.eta : "") } as T;
  if ("driver" in next && "driver" in old) {
    (merged as RideData).driver = next.driver || old.driver;
    (merged as RideData).vehicle = next.vehicle || old.vehicle;
  }
  if ("courier" in next && "courier" in old) (merged as DeliveryData).courier = next.courier || old.courier;
  if (next.stage < old.stage) return { ...merged, stage: old.stage, text: old.text, eta: old.eta };
  return merged;
}

// ── Stocks ────────────────────────────────────────────────────────────────────

const QUOTE_ALIASES: Record<string, string> = {
  NIFTY: ".NSEI", NIFTY50: ".NSEI", "NIFTY 50": ".NSEI", BANKNIFTY: ".NSEBANK", SENSEX: ".BSESN",
  DOW: ".DJI", SP500: ".SPX", "S&P": ".SPX", "S&P 500": ".SPX", NASDAQ: ".IXIC",
  BTC: "BTC.CM=", BITCOIN: "BTC.CM=", ETH: "ETH.CM=", ETHEREUM: "ETH.CM=", SOL: "SOL.CM=", DOGE: "DOGE.CM=",
  GOLD: "@GC.1", OIL: "@CL.1", USDINR: "INR=", "USD/INR": "INR=",
};

/**
 * The codes to try for what the user typed, most likely first: an alias
 * (NIFTY, BTC), Indian suffixes (RELIANCE.NS → RELIANCE-IN), the symbol as it
 * is (US), then the Indian exchange.
 */
export function quoteCandidates(input: string): string[] {
  const raw = input.trim().toUpperCase();
  if (!raw) return [];
  const alias = QUOTE_ALIASES[raw];
  if (alias) return [alias];
  const indian = /^(?:NSE:|BSE:)?([A-Z0-9&-]+?)(?:\.NS|\.BO|-IN)$/.exec(raw) ?? /^(?:NSE:|BSE:)([A-Z0-9&-]+)$/.exec(raw);
  if (indian) return [`${indian[1]}-IN`];
  const crypto = /^([A-Z]{2,6})[-/]?(USD|USDT)$/.exec(raw);
  if (crypto) return [`${crypto[1]}.CM=`];
  if (/^[.@]|=$/.test(raw)) return [raw];
  return [raw, `${raw}-IN`];
}

const num = (v: unknown): number => {
  const n = typeof v === "number" ? v : Number(String(v ?? "").replace(/[,%+]/g, ""));
  return Number.isFinite(n) ? n : 0;
};

/** One quote of CNBC's quote service → the stock card; null when it has none. */
export function parseQuote(q: Record<string, unknown> | null | undefined, symbol: string): Omit<StockData, "series"> | null {
  if (!q || num(q.code) !== 0 || q.last == null) return null;
  const price = num(q.last);
  const change = num(q.change);
  return {
    symbol,
    code: String(q.symbol ?? symbol),
    name: String(q.name ?? q.shortName ?? symbol),
    price,
    change,
    changePct: num(q.change_pct),
    currency: String(q.currencyCode ?? "USD"),
    prevClose: num(q.previous_day_closing) || price - change,
    marketOpen: String(q.curmktstatus ?? "") === "REG_MKT",
  };
}

/** Closing prices of the day's bars, thinned to at most `max` points. */
export function parseBars(json: unknown, max = 60): number[] {
  const bars = (json as { barData?: { priceBars?: { close?: unknown }[] } } | null)?.barData?.priceBars;
  if (!Array.isArray(bars)) return [];
  const closes = bars.map((b) => num(b.close)).filter((v) => v > 0);
  if (closes.length <= max) return closes;
  const step = closes.length / max;
  const out: number[] = [];
  for (let i = 0; i < max; i++) out.push(closes[Math.floor(i * step)]);
  out[out.length - 1] = closes[closes.length - 1];
  return out;
}

// ── Sports ────────────────────────────────────────────────────────────────────

export const SPORTS: { id: string; name: string }[] = [
  { id: "cricket", name: "Cricket" },
  { id: "soccer", name: "Football" },
  { id: "basketball", name: "Basketball" },
  { id: "tennis", name: "Tennis" },
  { id: "football", name: "NFL" },
  { id: "hockey", name: "Hockey" },
  { id: "baseball", name: "Baseball" },
  { id: "racing", name: "F1" },
];

type Json = Record<string, unknown>;
const arr = (v: unknown): Json[] => (Array.isArray(v) ? (v as Json[]) : []);
const str = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");

function teamOf(c: Json | undefined): TeamScore {
  return {
    abbr: str(c?.abbreviation) || str(c?.displayName).slice(0, 3).toUpperCase(),
    name: str(c?.displayName) || str(c?.name) || str(c?.abbreviation),
    score: str(c?.score),
    logo: str(c?.logo) || str(c?.logoDark),
    winner: c?.winner === true,
  };
}

/** ESPN's scoreboard header for one sport → every match it lists. */
export function parseScoreboard(json: unknown, sport: string): SportsData[] {
  const out: SportsData[] = [];
  for (const s of arr((json as Json | null)?.sports)) {
    for (const league of arr(s.leagues)) {
      for (const e of arr(league.events)) {
        const teams = arr(e.competitors);
        if (teams.length < 2) continue;
        const home = teams.find((t) => t.homeAway === "home") ?? teams[0];
        const away = teams.find((t) => t !== home) ?? teams[1];
        const type = ((e.fullStatus as Json | undefined)?.type ?? {}) as Json;
        const state = str(type.state) || str(e.status);
        out.push({
          eventId: str(e.id),
          sport,
          league: str(league.shortName) || str(league.name),
          state: state === "in" ? "in" : state === "post" ? "post" : "pre",
          status: str(type.shortDetail) || str(type.detail) || str(type.description) || str(e.summary),
          summary: str(e.summary) || str(type.detail),
          startsAt: Date.parse(str(e.date)) || 0,
          link: str(e.link),
          home: teamOf(home),
          away: teamOf(away),
        });
      }
    }
  }
  return out;
}

/** Matches with a followed team or league in their names, live ones first. */
export function followedMatches(all: SportsData[], follows: string[]): SportsData[] {
  const wanted = follows.map((f) => f.trim().toLowerCase()).filter(Boolean);
  if (!wanted.length) return [];
  const hit = (m: SportsData) => {
    const hay = [m.home.abbr, m.home.name, m.away.abbr, m.away.name, m.league].map((x) => x.toLowerCase());
    return wanted.some((w) => hay.some((x) => x === w || (w.length > 3 && x.includes(w))));
  };
  const order = { in: 0, pre: 1, post: 2 };
  return all.filter(hit).sort((a, b) => order[a.state] - order[b.state] || a.startsAt - b.startsAt);
}

/** "182/4 (18.2 ov)" → "182/4": what fits next to a team in the pill. */
export function shortScore(score: string): string {
  const s = score.trim();
  if (!s) return "–";
  const last = s.split("&").pop()!.trim();
  return last.replace(/\s*\(.*$/, "") || s;
}

// ── Routes ────────────────────────────────────────────────────────────────────

/** Google's encoded polyline (precision 5) → [lon, lat] points. */
export function decodePolyline(encoded: string): [number, number][] {
  const out: [number, number][] = [];
  let i = 0, lat = 0, lon = 0;
  while (i < encoded.length) {
    for (const which of [0, 1]) {
      let shift = 0, result = 0, byte: number;
      do {
        byte = encoded.charCodeAt(i++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && i < encoded.length);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (which === 0) lat += delta; else lon += delta;
    }
    out.push([lon / 1e5, lat / 1e5]);
  }
  return out;
}

function instruction(type: string, modifier: string, name: string, exit: number | undefined): string {
  const onto = name ? ` onto ${name}` : "";
  const on = name ? ` on ${name}` : "";
  switch (type) {
    case "depart": return `Head out${on}`;
    case "arrive": return "You have arrived";
    case "roundabout":
    case "rotary": return `At the roundabout take exit ${exit ?? 1}${onto}`;
    case "merge": return `Merge${onto}`;
    case "on ramp": return `Take the ramp${onto}`;
    case "off ramp": return `Take the exit${onto}`;
    case "fork": return `Keep ${modifier.includes("left") ? "left" : "right"}${onto}`;
    case "end of road": return `Turn ${modifier.replace("sharp ", "").replace("slight ", "")}${onto}`;
    case "new name":
    case "continue": return modifier === "uturn" ? "Make a U-turn" : `Continue${on}`;
    default:
      if (modifier === "uturn") return "Make a U-turn";
      if (modifier === "straight" || !modifier) return `Continue${on}`;
      return `${modifier.startsWith("slight") ? "Bear" : "Turn"} ${modifier.replace("slight ", "").replace("sharp ", "sharp ")}${onto}`;
  }
}

/** OSRM's answer → the navigation card; null when it found no route. */
export function parseRoute(json: unknown, origin: string, destination: string, now: number): NavData | null {
  const route = arr((json as Json | null)?.routes)[0];
  if (!route) return null;
  const steps: NavStep[] = [];
  for (const leg of arr(route.legs)) {
    for (const s of arr(leg.steps)) {
      const man = (s.maneuver ?? {}) as Json;
      const type = str(man.type);
      const modifier = str(man.modifier);
      steps.push({
        text: instruction(type, modifier, str(s.name), typeof man.exit === "number" ? man.exit : undefined),
        distance: num(s.distance),
        modifier: type === "arrive" ? "arrive" : type.includes("roundabout") || type === "rotary" ? "roundabout" : modifier || "straight",
      });
    }
  }
  if (!steps.length) return null;
  const full = typeof route.geometry === "string" ? decodePolyline(route.geometry) : [];
  const stride = Math.max(1, Math.ceil(full.length / 120));
  const line = full.filter((_, i) => i % stride === 0 || i === full.length - 1);
  const duration = num(route.duration);
  return {
    destination, origin, steps, stepIndex: 0,
    distance: num(route.distance), duration,
    etaAt: now + duration * 1000, line, source: "route",
  };
}

/** Metres still to go from the current step on. */
export function navRemaining(n: NavData): number {
  return n.steps.slice(n.stepIndex).reduce((sum, s) => sum + s.distance, 0);
}

/** The activities on screen. */
export const Live = new LiveStore();

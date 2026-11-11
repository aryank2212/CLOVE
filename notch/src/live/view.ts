// (English only for now: these strings are not in the translation tables yet.)
// The live activities on screen: what the compact pill wears on each side
// (and the bubble beside it), and the card the island opens into. One builder
// per kind; each returns its elements and an `update` that is cheap enough to
// run on every sync.

import { h, clear, svg } from "../views/dom";
import { icon, turnIcon, type LiveIcon } from "./icons";
import {
  DELIVERY_STAGES, Live, RIDE_STAGES, SPORTS, brandById, clock, fmtDistance, fmtMoney, is, linkOf, mediaPosition,
  navRemaining, parseDuration, shortDuration, shortScore, stopwatchMs, timerLeft,
  type AnyActivity, type LiveActivity, type LiveKind, type MediaData, type MediaSource, type SportsData,
} from "../core/live";
import { LiveCtl } from "./control";
import { State } from "../core/state";
import { openUnreadApp, type ViewActions, type ViewHost } from "../views/views";
import { APP_LOGOS } from "../views/logos";

// ── Colours ───────────────────────────────────────────────────────────────────

const GREEN = "#30D158";
const RED = "#FF453A";
const ORANGE = "#FF9F0A";
const BLUE = "#0A84FF";
const CLOVE = "#FB923C";

const SOURCE: Record<MediaSource, { name: string; color: string }> = {
  spotify: { name: "Spotify", color: "#1ED760" },
  youtube: { name: "YouTube", color: "#FF3B30" },
  ytmusic: { name: "YouTube Music", color: "#FF3B30" },
  applemusic: { name: "Apple Music", color: "#FA2D48" },
  browser: { name: "Browser", color: "#8AB4F8" },
  video: { name: "Video", color: "#BF5AF2" },
  music: { name: "Music", color: "#64D2FF" },
};

const KIND_ICON: Record<LiveKind, LiveIcon> = {
  call: "phone", voice: "mic", auth: "lock", payment: "wallet", timer: "timer", stopwatch: "stopwatch",
  memo: "wave", recording: "record", nav: "arrowUp", ride: "car", delivery: "box", media: "music",
  sports: "trophy", stock: "chart", device: "headphones", battery: "battery", hotspot: "link", camera: "camera",
};

/** The colour an activity is known by: its service's, else its kind's. */
export function accentOf(a: LiveActivity): string {
  if (is(a, "media")) return SOURCE[a.data.source].color;
  if (is(a, "ride") || is(a, "delivery")) return brandById(a.data.brand)?.color ?? ORANGE;
  if (is(a, "stock")) return a.data.change >= 0 ? GREEN : RED;
  if (is(a, "battery")) return a.data.event === "low" ? RED : GREEN;
  if (is(a, "auth")) return a.data.ok === false ? RED : GREEN;
  if (is(a, "call")) return a.data.state === "missed" ? RED : GREEN;
  switch (a.kind) {
    case "voice": return CLOVE;
    case "timer": case "stopwatch": return ORANGE;
    case "memo": case "recording": return RED;
    case "nav": return BLUE;
    case "sports": return "#FFD60A";
    default: return GREEN;
  }
}

// ── Small pieces ──────────────────────────────────────────────────────────────

const div = (cls: string, ...children: (Node | string | null)[]) => h("div", { class: cls }, ...children);
const span = (cls: string, text = "") => h("span", { class: cls, text });

function setText(el: HTMLElement, text: string) {
  if (el.textContent !== text) el.textContent = text;
}

/** Bars that dance while something plays (CSS does the dancing). */
function eqBars(count = 4): HTMLElement {
  const el = div("lv-eq");
  for (let i = 0; i < count; i++) el.append(h("i", {}));
  return el;
}

/** A brand's tile: its colour and first letter. */
function brandTile(brandId: string, size: number): HTMLElement {
  const b = brandById(brandId);
  const el = div("lv-brand", (b?.name ?? brandId).charAt(0));
  el.style.cssText = `width:${size}px;height:${size}px;font-size:${Math.round(size * 0.52)}px;border-radius:${Math.round(size * 0.3)}px;background:${b?.color ?? "#333"};color:${b?.ink ?? "#fff"}`;
  return el;
}

/** A ring that fills with `fraction` (0…1), with room for a label inside. */
function ring(size: number, stroke: number): { el: HTMLElement; set(fraction: number, color: string, label?: string): void } {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = document.createElementNS(ns, "svg");
  svgEl.setAttribute("width", String(size));
  svgEl.setAttribute("height", String(size));
  const mk = (cls: string) => {
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", String(size / 2));
    circle.setAttribute("cy", String(size / 2));
    circle.setAttribute("r", String(r));
    circle.setAttribute("fill", "none");
    circle.setAttribute("stroke-width", String(stroke));
    circle.setAttribute("class", cls);
    return circle;
  };
  const track = mk("lv-ring-track");
  const fill = mk("lv-ring-fill");
  fill.setAttribute("stroke-dasharray", String(c));
  fill.setAttribute("stroke-linecap", "round");
  fill.setAttribute("transform", `rotate(-90 ${size / 2} ${size / 2})`);
  svgEl.append(track, fill);
  const label = span("lv-ring-label");
  const el = div("lv-ring", svgEl as unknown as Node, label);
  el.style.cssText = `width:${size}px;height:${size}px`;
  return {
    el,
    set(fraction, color, text = "") {
      fill.setAttribute("stroke-dashoffset", String(c * (1 - Math.max(0, Math.min(1, fraction)))));
      fill.setAttribute("stroke", color);
      setText(label, text);
    },
  };
}

function roundBtn(name: LiveIcon, cls: string, title: string, onClick: () => void, size = 18): HTMLButtonElement {
  return h("button", { class: `lv-btn ${cls}`, title, onclick: (e: Event) => { e.stopPropagation(); onClick(); } }, icon(name, size));
}

function pill(label: string, cls: string, onClick: () => void): HTMLButtonElement {
  return h("button", { class: `lv-pill ${cls}`, onclick: (e: Event) => { e.stopPropagation(); onClick(); } }, label);
}

function cover(size: number): { el: HTMLElement; set(m: MediaData): void } {
  const img = h("img", { class: "lv-art-img", alt: "" });
  const fallback = div("lv-art-fallback", icon("music", Math.round(size * 0.46)));
  const el = div("lv-art", fallback, img);
  el.style.cssText = `width:${size}px;height:${size}px;border-radius:${Math.round(size * 0.24)}px`;
  let shown = "";
  return {
    el,
    set(m) {
      const src = LiveCtl.artFor(m) ?? "";
      if (src !== shown) {
        shown = src;
        if (src) img.src = src;
        img.style.opacity = src ? "1" : "0";
      }
      el.style.setProperty("--accent", SOURCE[m.source].color);
    },
  };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter((p) => /\p{L}/u.test(p));
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

/** Level bars for a voice: the newest `count` levels, oldest left. */
function levelBars(count: number): { el: HTMLElement; set(levels: number[]): void } {
  const el = div("lv-levels");
  const bars: HTMLElement[] = [];
  for (let i = 0; i < count; i++) {
    const b = h("i", {});
    bars.push(b);
    el.append(b);
  }
  return {
    el,
    set(levels) {
      const tail = levels.slice(-count);
      const pad = count - tail.length;
      bars.forEach((b, i) => {
        const v = i < pad ? 0 : tail[i - pad];
        b.style.transform = `scaleY(${(0.12 + 0.88 * Math.min(1, v)).toFixed(3)})`;
      });
    },
  };
}

const deviceIcon = (type: string): LiveIcon =>
  type === "headphones" ? "headphones" : type === "phone" ? "handset" : type === "mouse" ? "mouse" : type === "keyboard" ? "keyboard" : "bolt";

const batteryColor = (percent: number, charging: boolean) => (charging ? GREEN : percent <= 20 ? RED : percent <= 40 ? ORANGE : GREEN);

// ── The compact pill ──────────────────────────────────────────────────────────

interface Slot {
  lead: Node[];
  trail: Node[];
  update(a: AnyActivity, now: number): void;
}

function compactSlot(a: AnyActivity): Slot {
  const accent = accentOf(a);
  const glyph = (name: LiveIcon, color = accent) => {
    const el = div("lc-glyph", icon(name, 15));
    el.style.color = color;
    return el;
  };
  const value = span("lc-value");
  value.style.color = accent;
  const label = span("lc-label");

  switch (a.kind) {
    case "media": {
      const art = cover(22);
      const bars = eqBars(4);
      return {
        lead: [art.el, label], trail: [bars],
        update(x) {
          if (!is(x, "media")) return;
          art.set(x.data);
          setText(label, x.data.title);
          bars.style.color = SOURCE[x.data.source].color;
          bars.classList.toggle("paused", !x.data.playing);
        },
      };
    }
    case "call":
      return {
        lead: [glyph(a.data.video ? "video" : "phone"), label], trail: [value],
        update(x, now) {
          if (!is(x, "call")) return;
          setText(label, x.data.name);
          value.style.color = accentOf(x);
          value.classList.toggle("lv-blink", x.data.state === "incoming");
          setText(value, x.data.state === "incoming" ? "Incoming" : x.data.state === "missed" ? "Missed" : clock((now - x.data.since) / 1000));
        },
      };
    case "voice": {
      const bars = eqBars(5);
      bars.style.color = CLOVE;
      return {
        lead: [bars], trail: [value],
        update(x) {
          if (!is(x, "voice")) return;
          bars.classList.toggle("paused", x.data.phase === "thinking" || x.data.phase === "working");
          setText(value, { listening: "Listening", thinking: "Thinking", working: "Working", speaking: "Speaking" }[x.data.phase]);
        },
      };
    }
    case "timer":
      return {
        lead: [glyph("timer"), label], trail: [value],
        update(x, now) {
          if (!is(x, "timer")) return;
          setText(label, x.data.label === "Timer" ? "" : x.data.label);
          value.classList.toggle("lv-blink", x.data.done);
          setText(value, x.data.done ? "Done" : clock(Math.ceil(timerLeft(x.data, now))));
        },
      };
    case "stopwatch":
      return {
        lead: [glyph("stopwatch")], trail: [value],
        update(x, now) {
          if (is(x, "stopwatch")) setText(value, clock(stopwatchMs(x.data, now) / 1000));
        },
      };
    case "memo": {
      const dot = div("lc-rec");
      const bars = levelBars(8);
      return {
        lead: [dot, bars.el], trail: [value],
        update(x, now) {
          if (!is(x, "memo")) return;
          const rec = x.data.state === "recording";
          dot.classList.toggle("on", rec);
          bars.set(x.data.levels);
          setText(value, rec ? clock((now - x.data.since) / 1000) : "Saved");
        },
      };
    }
    case "recording": {
      const dot = div("lc-rec on");
      return {
        lead: [dot, label], trail: [value],
        update(x, now) {
          if (!is(x, "recording")) return;
          setText(label, "Recording");
          setText(value, clock((now - x.data.since) / 1000));
        },
      };
    }
    case "nav": {
      const tile = div("lc-turn");
      let shown = "";
      return {
        lead: [tile, label], trail: [value],
        update(x) {
          if (!is(x, "nav")) return;
          const step = x.data.steps[x.data.stepIndex];
          if (step && step.modifier !== shown) {
            shown = step.modifier;
            clear(tile);
            tile.append(icon(turnIcon(step.modifier), 14, 2.4));
          }
          setText(label, step?.distance ? fmtDistance(step.distance) : "");
          setText(value, x.data.duration ? shortDuration(x.data.duration) : x.data.destination);
        },
      };
    }
    case "ride":
    case "delivery": {
      const tile = brandTile(a.data.brand, 22);
      return {
        lead: [tile, label], trail: [value],
        update(x) {
          if (is(x, "ride")) {
            setText(label, ["Finding", "On the way", "Arrived", "On trip", "Completed"][x.data.stage] ?? "");
            setText(value, x.data.stage <= 2 && x.data.otp ? `PIN ${x.data.otp}` : x.data.eta);
          } else if (is(x, "delivery")) {
            setText(label, ["Confirmed", "Packed", "On the way", "Delivered"][x.data.stage] ?? "");
            setText(value, x.data.eta);
          }
        },
      };
    }
    case "sports": {
      const lead = span("lc-score");
      const trail = span("lc-score");
      const live = div("lc-live");
      return {
        lead: [live, lead], trail: [trail],
        update(x) {
          if (!is(x, "sports")) return;
          live.classList.toggle("on", x.data.state === "in");
          setText(lead, `${x.data.home.abbr} ${shortScore(x.data.home.score)}`);
          setText(trail, `${shortScore(x.data.away.score)} ${x.data.away.abbr}`);
        },
      };
    }
    case "stock":
      return {
        lead: [label], trail: [value],
        update(x) {
          if (!is(x, "stock")) return;
          setText(label, x.data.symbol);
          value.style.color = accentOf(x);
          setText(value, `${x.data.changePct >= 0 ? "▲" : "▼"} ${Math.abs(x.data.changePct).toFixed(2)}%`);
        },
      };
    case "auth": {
      const lead = div("lc-glyph");
      const trail = div("lc-glyph");
      let shown = "";
      return {
        lead: [lead], trail: [trail],
        update(x) {
          if (!is(x, "auth")) return;
          const key = `${x.data.method}:${x.data.ok}`;
          if (key === shown) return;
          shown = key;
          clear(lead);
          clear(trail);
          const locked = x.data.ok !== true;
          lead.append(icon(x.data.method === "face" ? "faceId" : x.data.method === "fingerprint" ? "fingerprint" : locked ? "lock" : "unlock", 15));
          lead.style.color = accentOf(x);
          if (x.data.ok == null) trail.append(div("lc-spinner"));
          else trail.append(icon(x.data.ok ? "check" : "x", 15, 2.6));
          trail.style.color = accentOf(x);
        },
      };
    }
    case "payment":
      return {
        lead: [glyph("check")], trail: [value],
        update(x) {
          if (is(x, "payment")) setText(value, fmtMoney(x.data.amount, x.data.currency));
        },
      };
    case "device": {
      const r = ring(20, 3);
      return {
        lead: [glyph(deviceIcon(a.data.type), "#fff"), label], trail: [r.el],
        update(x) {
          if (!is(x, "device")) return;
          setText(label, x.data.name);
          r.el.style.display = x.data.percent == null ? "none" : "";
          r.set((x.data.percent ?? 0) / 100, batteryColor(x.data.percent ?? 100, x.data.charging));
        },
      };
    }
    case "battery":
      return {
        lead: [glyph(a.data.charging ? "bolt" : "battery")], trail: [value],
        update(x) {
          if (!is(x, "battery")) return;
          value.style.color = accentOf(x);
          setText(value, `${x.data.percent}%`);
        },
      };
    case "hotspot":
      return {
        lead: [glyph("link")], trail: [value],
        update(x) {
          if (is(x, "hotspot")) setText(value, x.data.clients ? String(x.data.clients) : "On");
        },
      };
    case "camera":
      return {
        lead: [glyph("camera")], trail: [label],
        update(x) {
          if (is(x, "camera")) setText(label, x.data.apps[0] ?? "Camera");
        },
      };
  }
}

/** What separates one compact layout from the next: a new one is built when it changes. */
function slotKey(a: LiveActivity): string {
  const extra = is(a, "call") ? String(a.data.video) : is(a, "ride") || is(a, "delivery") ? a.data.brand : is(a, "battery") ? String(a.data.charging) : is(a, "device") ? a.data.type : "";
  return `${a.id}|${a.kind}|${extra}`;
}

export class CompactLive {
  /** Both sides of the pill, laid out by the island between CLOVE and the grid. */
  readonly el = div("live-compact");
  /** The circle next to the pill: unread notifications, and the way into the launcher. */
  readonly bubble = h("button", { class: "live-bubble", title: "" });
  private lead = div("lc-lead");
  private trail = div("lc-trail");
  private dots = div("lc-dots");
  private micDot = div("lc-dot mic");
  private camDot = div("lc-dot cam");
  private key = "";
  private slot: Slot | null = null;
  private bubbleKey = "";

  constructor() {
    this.dots.append(this.camDot, this.micDot);
    this.el.append(this.lead, this.trail, this.dots);
  }

  /** True when the pill has something to wear. */
  get active(): boolean {
    return this.slot != null;
  }

  /** Redraws both sides; answers with the width the content wants. */
  sync(now: number): number {
    const primary = Live.primary(now) as AnyActivity | null;
    const key = primary ? slotKey(primary) : "";
    if (key !== this.key) {
      this.key = key;
      this.slot = primary ? compactSlot(primary) : null;
      this.lead.replaceChildren(...(this.slot?.lead ?? []));
      this.trail.replaceChildren(...(this.slot?.trail ?? []));
      // The new content fades in on both sides of the pill.
      this.el.classList.remove("swap");
      void this.el.offsetWidth;
      this.el.classList.add("swap");
    }
    if (primary) this.slot?.update(primary, now);

    const sys = LiveCtl.system;
    // CLOVE listens all the time (its mic button says so): the dot is for anything else on the microphone.
    const micApps = (sys?.mic ?? []).filter((x) => x !== "CLOVE");
    const mic = micApps.length > 0;
    const cam = (sys?.camera.length ?? 0) > 0;
    this.micDot.classList.toggle("on", mic);
    this.camDot.classList.toggle("on", cam);
    this.micDot.title = mic ? `Microphone: ${micApps.join(", ")}` : "";
    this.camDot.title = cam ? `Camera: ${sys!.camera.join(", ")}` : "";
    this.dots.classList.toggle("on", mic || cam);

    if (!primary && !mic && !cam) return 0;
    return this.lead.offsetWidth + this.trail.offsetWidth + this.dots.offsetWidth;
  }

  /**
   * The circle beside the pill: the app with unread messages and how many, else the launcher's mark.
   * `logo` is an SVG path (views/logos.ts), `letter` stands in when the app has none.
   */
  setBubble(unread: { logo?: string; letter: string; count: number } | null) {
    const key = unread ? `${unread.logo ?? unread.letter}|${unread.count}` : "grid";
    if (key === this.bubbleKey) return;
    this.bubbleKey = key;
    clear(this.bubble);
    if (unread) {
      this.bubble.append(
        unread.logo ? svg(unread.logo, 16) : h("b", { class: "live-bubble-letter", text: unread.letter }),
        h("span", { class: "live-bubble-count", text: unread.count > 9 ? "9+" : String(unread.count) }));
      this.bubble.title = `${unread.count} unread · open the launcher`;
    } else {
      this.bubble.append(icon("grid", 14));
      this.bubble.title = "Timer, memo, status and more";
    }
    this.bubble.classList.toggle("unread", unread != null);
  }
}

/** A few words for an activity: tooltips and the dock. */
export function titleOf(a: LiveActivity): string {
  if (is(a, "media")) return `${a.data.title}${a.data.artist ? ` · ${a.data.artist}` : ""}`;
  if (is(a, "call")) return `${a.data.name} · ${a.data.app}`;
  if (is(a, "timer")) return a.data.label;
  if (is(a, "ride") || is(a, "delivery")) return brandById(a.data.brand)?.name ?? a.data.brand;
  if (is(a, "sports")) return `${a.data.home.abbr} v ${a.data.away.abbr}`;
  if (is(a, "stock")) return a.data.symbol;
  if (is(a, "nav")) return `To ${a.data.destination}`;
  if (is(a, "device")) return a.data.name;
  return {
    voice: "CLOVE", auth: "Authentication", payment: "Payment", stopwatch: "Stopwatch", memo: "Voice memo",
    recording: "Screen recording", battery: "Battery", hotspot: "Hotspot", camera: "Camera",
  }[a.kind as string] ?? a.kind;
}

// ── The cards ─────────────────────────────────────────────────────────────────

interface Card {
  el: HTMLElement;
  update(a: AnyActivity, now: number): void;
}

const W = 440;

/** The island's size for an activity's card (dock not included). */
export function cardSize(a: LiveActivity): { w: number; h: number } {
  switch (a.kind) {
    case "media": return { w: W, h: 176 };
    case "nav": return { w: W, h: 184 };
    case "ride":
    case "delivery": return { w: W, h: 172 };
    case "stock": return { w: W, h: 180 };
    case "sports": return { w: W, h: 138 };
    case "voice": return { w: W, h: 134 };
    case "auth": return { w: 196, h: 138 };
    case "payment": return { w: 300, h: 138 };
    case "device":
    case "battery":
    case "camera": return { w: 350, h: 92 };
    case "timer":
    case "stopwatch": return { w: 420, h: 92 };
    default: return { w: 400, h: 92 };
  }
}

function buildCard(a: AnyActivity, actions: ViewActions): Card {
  switch (a.kind) {
    case "media": return mediaCard();
    case "call": return callCard();
    case "voice": return voiceCard();
    case "timer": return timerCard();
    case "stopwatch": return stopwatchCard();
    case "memo": return memoCard();
    case "recording": return recordingCard();
    case "nav": return navCard();
    case "ride":
    case "delivery": return trackCard(a.data.brand);
    case "sports": return sportsCard();
    case "stock": return stockCard();
    case "auth": return authCard();
    case "payment": return paymentCard();
    case "device": return deviceCard();
    case "battery": return batteryCard();
    case "hotspot": return hotspotCard();
    case "camera": return cameraCard(actions);
  }
}

function mediaCard(): Card {
  const art = cover(58);
  const title = div("lv-title");
  const sub = div("lv-sub");
  const source = span("lv-source");
  const bars = eqBars(5);
  const elapsed = span("lv-time");
  const left = span("lv-time");
  const fill = div("lv-bar-fill");
  const bar = div("lv-bar", fill);
  const play = roundBtn("pause", "ghost big", "Play / pause", () => void LiveCtl.mediaControl("toggle"), 26);
  const prev = roundBtn("prev", "ghost", "Previous", () => void LiveCtl.mediaControl("previous"), 20);
  const next = roundBtn("next", "ghost", "Next", () => void LiveCtl.mediaControl("next"), 20);
  const open = roundBtn("external", "ghost small", "Open the player", () => LiveCtl.open("media"), 15);
  let playing: boolean | null = null;
  let current: MediaData | null = null;
  bar.addEventListener("click", (e) => {
    if (!current || !current.canSeek || current.duration <= 0) return;
    const r = bar.getBoundingClientRect();
    void LiveCtl.mediaControl("seek", Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * current.duration);
  });
  const el = div("lv-card lv-media",
    div("lv-row", art.el, div("lv-col grow", title, sub), div("lv-col end", bars, source)),
    div("lv-row lv-progress", elapsed, bar, left),
    div("lv-row lv-controls", div("lv-side"), prev, play, next, div("lv-side end", open)),
  );
  return {
    el,
    update(a, now) {
      if (!is(a, "media")) return;
      const m = a.data;
      current = m;
      art.set(m);
      el.style.setProperty("--accent", SOURCE[m.source].color);
      setText(title, m.title);
      setText(sub, m.artist || m.album || m.app);
      setText(source, SOURCE[m.source].name === "Browser" ? m.app || "Browser" : SOURCE[m.source].name);
      bars.classList.toggle("paused", !m.playing);
      if (playing !== m.playing) {
        playing = m.playing;
        clear(play);
        play.append(icon(m.playing ? "pause" : "play", 26));
      }
      prev.disabled = !m.canPrev;
      next.disabled = !m.canNext;
      const p = mediaPosition(m, now);
      const known = m.duration > 0;
      setText(elapsed, clock(p));
      setText(left, known ? `-${clock(m.duration - p)}` : "Live");
      fill.style.width = known ? `${(p / m.duration) * 100}%` : "100%";
      bar.classList.toggle("seekable", m.canSeek && known);
    },
  };
}

function callCard(): Card {
  const avatar = div("lv-avatar");
  const sub = div("lv-sub");
  const title = div("lv-title");
  const decline = roundBtn("phoneDown", "red", "Decline", () => LiveCtl.endCall(), 22);
  const accept = roundBtn("phone", "green", "Answer", () => LiveCtl.acceptCall(), 20);
  let video: boolean | null = null;
  const el = div("lv-card lv-line", avatar, div("lv-col grow", sub, title), decline, accept);
  return {
    el,
    update(a, now) {
      if (!is(a, "call")) return;
      const c = a.data;
      setText(avatar, initials(c.name));
      setText(title, c.name);
      const what = c.video ? "video call" : "call";
      setText(sub, c.state === "incoming" ? `Incoming ${what} · ${c.app}` : c.state === "missed" ? `Missed ${what} · ${c.app}` : `${c.app} · ${clock((now - c.since) / 1000)}`);
      accept.style.display = c.state === "incoming" ? "" : "none";
      el.classList.toggle("ringing", c.state === "incoming");
      decline.title = c.state === "incoming" ? "Decline" : c.state === "missed" ? "Dismiss" : "End";
      if (video !== c.video) {
        video = c.video;
        clear(accept);
        accept.append(icon(c.video ? "video" : "phone", 20));
      }
    },
  };
}

function voiceCard(): Card {
  const orb = div("lv-orb", eqBars(5));
  const phase = div("lv-sub");
  const heard = div("lv-heard");
  const reply = div("lv-reply");
  const el = div("lv-card lv-voice", orb, div("lv-col grow", phase, heard, reply));
  return {
    el,
    update(a) {
      if (!is(a, "voice")) return;
      const v = a.data;
      el.dataset.phase = v.phase;
      setText(phase, { listening: "Listening…", thinking: "Thinking…", working: "Working on it…", speaking: "CLOVE" }[v.phase]);
      setText(heard, v.heard ? `“${v.heard}”` : v.phase === "listening" ? "Say what you need: open an app, run a command, set a timer…" : "");
      setText(reply, v.reply);
    },
  };
}

function timerCard(): Card {
  let id = "";
  const toggle = roundBtn("pause", "orange", "Pause", () => LiveCtl.toggleTimer(id), 20);
  const cancel = roundBtn("x", "grey", "Cancel", () => LiveCtl.dismiss(id), 20);
  const plus = pill("+1 min", "ghost", () => LiveCtl.addToTimer(id, 60));
  const repeat = pill("Repeat", "ghost", () => LiveCtl.restartTimer(id));
  const label = span("lv-timer-label");
  const time = span("lv-timer-time");
  const fill = div("lv-bar-fill");
  let paused: boolean | null = null;
  const el = div("lv-card lv-line lv-timer", toggle, cancel, plus, repeat, div("grow"), label, time, div("lv-bar lv-timer-bar", fill));
  return {
    el,
    update(a, now) {
      if (!is(a, "timer")) return;
      id = a.id;
      const t = a.data;
      const left = timerLeft(t, now);
      setText(label, t.done ? `${t.label} done` : t.label);
      setText(time, clock(Math.ceil(left)));
      el.classList.toggle("done", t.done);
      toggle.style.display = t.done ? "none" : "";
      plus.style.display = t.done ? "none" : "";
      repeat.style.display = t.done ? "" : "none";
      fill.style.width = `${t.duration > 0 ? (1 - left / t.duration) * 100 : 100}%`;
      const isPaused = t.pausedLeft != null;
      if (paused !== isPaused) {
        paused = isPaused;
        clear(toggle);
        toggle.append(icon(isPaused ? "play" : "pause", 20));
        toggle.title = isPaused ? "Resume" : "Pause";
      }
    },
  };
}

function stopwatchCard(): Card {
  const toggle = roundBtn("pause", "orange", "Stop", () => LiveCtl.stopwatch("toggle"), 20);
  const reset = roundBtn("x", "grey", "Reset", () => LiveCtl.stopwatch("reset"), 20);
  const lap = pill("Lap", "ghost", () => LiveCtl.stopwatch("lap"));
  const label = span("lv-timer-label");
  const time = span("lv-timer-time");
  let running: boolean | null = null;
  const el = div("lv-card lv-line lv-timer", toggle, reset, lap, div("grow"), label, time);
  return {
    el,
    update(a, now) {
      if (!is(a, "stopwatch")) return;
      const ms = stopwatchMs(a.data, now);
      setText(time, `${clock(ms / 1000)}.${Math.floor((ms % 1000) / 100)}`);
      const laps = a.data.laps;
      setText(label, laps.length ? `Lap ${laps.length} · ${clock((laps[laps.length - 1] - (laps[laps.length - 2] ?? 0)) / 1000)}` : "Stopwatch");
      const on = a.data.since != null;
      lap.style.display = on ? "" : "none";
      if (running !== on) {
        running = on;
        clear(toggle);
        toggle.append(icon(on ? "pause" : "play", 20));
      }
    },
  };
}

function memoCard(): Card {
  const dot = div("lc-rec on");
  const title = div("lv-title");
  const sub = div("lv-sub");
  const bars = levelBars(28);
  const time = span("lv-timer-time small red");
  const stop = roundBtn("stop", "red-ring", "Stop", () => void LiveCtl.memoStop(), 18);
  const play = pill("Play", "ghost", () => {});
  const show = pill("Show", "ghost", () => {});
  let path = "";
  play.onclick = (e) => { e.stopPropagation(); LiveCtl.playFile(path); };
  show.onclick = (e) => { e.stopPropagation(); LiveCtl.reveal(path); };
  const el = div("lv-card lv-line", dot, div("lv-col", title, sub), bars.el, div("grow"), time, play, show, stop);
  return {
    el,
    update(a, now) {
      if (!is(a, "memo")) return;
      path = a.data.path;
      const rec = a.data.state === "recording";
      dot.classList.toggle("on", rec);
      dot.style.display = rec ? "" : "none";
      setText(title, rec ? "Voice memo" : "Memo saved");
      setText(sub, rec ? "Recording" : a.data.path.split("/").pop() ?? "");
      bars.el.style.display = rec ? "" : "none";
      bars.set(a.data.levels);
      setText(time, clock(rec ? (now - a.data.since) / 1000 : a.data.seconds));
      stop.style.display = rec ? "" : "none";
      play.style.display = rec ? "none" : "";
      show.style.display = rec ? "none" : "";
    },
  };
}

function recordingCard(): Card {
  let pid = 0;
  const time = span("lv-rec-time");
  const sub = div("lv-sub");
  const stop = roundBtn("stop", "red-ring", "Stop recording", () => LiveCtl.stopRecording(pid), 18);
  const el = div("lv-card lv-line", div("lv-col grow", div("lv-row tight", div("lc-rec on"), time), div("lv-title", "Screen Recording"), sub), stop);
  return {
    el,
    update(a, now) {
      if (!is(a, "recording")) return;
      pid = a.data.pid;
      setText(time, clock((now - a.data.since) / 1000));
      setText(sub, a.data.app === "Screen recording" ? "" : a.data.app);
    },
  };
}

/** The route as a small drawing, with where the current step starts. */
function routeMap(): { el: HTMLElement; set(line: [number, number][], fraction: number): void } {
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = document.createElementNS(ns, "svg");
  svgEl.setAttribute("viewBox", "0 0 132 104");
  const mk = (tag: string, cls: string) => {
    const e = document.createElementNS(ns, tag);
    e.setAttribute("class", cls);
    svgEl.append(e);
    return e;
  };
  const ahead = mk("polyline", "lv-map-ahead");
  const done = mk("polyline", "lv-map-done");
  const end = mk("circle", "lv-map-end");
  const me = mk("circle", "lv-map-me");
  const el = div("lv-map", svgEl as unknown as Node);
  let key = "";
  let pts: [number, number][] = [];
  return {
    el,
    set(line, fraction) {
      const k = `${line.length}:${line[0]?.join(",")}:${line[line.length - 1]?.join(",")}`;
      if (k !== key) {
        key = k;
        pts = [];
        if (line.length > 1) {
          const lons = line.map((p) => p[0]);
          const lats = line.map((p) => p[1]);
          const minX = Math.min(...lons), maxX = Math.max(...lons), minY = Math.min(...lats), maxY = Math.max(...lats);
          // A degree of longitude is shorter than one of latitude away from the equator.
          const squash = Math.cos(((minY + maxY) / 2) * Math.PI / 180);
          const spanX = Math.max(1e-6, (maxX - minX) * squash), spanY = Math.max(1e-6, maxY - minY);
          const scale = Math.min(108 / spanX, 80 / spanY);
          const ox = (132 - spanX * scale) / 2, oy = (104 - spanY * scale) / 2;
          pts = line.map(([lon, lat]) => [ox + (lon - minX) * squash * scale, oy + (maxY - lat) * scale]);
        }
        ahead.setAttribute("points", pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" "));
        const last = pts[pts.length - 1];
        end.setAttribute("cx", String(last?.[0] ?? -10));
        end.setAttribute("cy", String(last?.[1] ?? -10));
        end.setAttribute("r", "4");
      }
      el.classList.toggle("empty", pts.length < 2);
      if (pts.length < 2) return;
      const at = Math.max(0, Math.min(pts.length - 1, Math.round(fraction * (pts.length - 1))));
      done.setAttribute("points", pts.slice(0, at + 1).map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" "));
      me.setAttribute("cx", String(pts[at][0]));
      me.setAttribute("cy", String(pts[at][1]));
      me.setAttribute("r", "4.5");
    },
  };
}

function navCard(): Card {
  const turn = div("lv-turn");
  const dist = div("lv-nav-dist");
  const text = div("lv-nav-text");
  const eta = div("lv-nav-eta");
  const map = routeMap();
  const prev = roundBtn("chevLeft", "grey small", "Previous step", () => LiveCtl.navStep(-1), 16);
  const next = roundBtn("chevRight", "grey small", "Next step", () => LiveCtl.navStep(1), 16);
  const end = pill("End", "red", () => LiveCtl.endNav());
  const count = span("lv-sub");
  let shown = "";
  const el = div("lv-card lv-nav",
    div("lv-row top", div("lv-col grow", div("lv-row", turn, div("lv-col grow", dist, text)), eta), map.el),
    div("lv-row lv-nav-foot", prev, next, count, div("grow"), end),
  );
  return {
    el,
    update(a) {
      if (!is(a, "nav")) return;
      const n = a.data;
      const step = n.steps[n.stepIndex];
      if (step && step.modifier !== shown) {
        shown = step.modifier;
        clear(turn);
        turn.append(icon(turnIcon(step.modifier), 30, 2.4));
      }
      setText(dist, step?.distance ? fmtDistance(step.distance) : step?.modifier === "arrive" ? "Arrived" : "");
      setText(text, step?.text ?? "");
      const left = navRemaining(n);
      const steps = n.steps.length > 1;
      prev.style.display = next.style.display = count.style.display = steps ? "" : "none";
      prev.disabled = n.stepIndex === 0;
      next.disabled = n.stepIndex >= n.steps.length - 1;
      setText(count, `Step ${n.stepIndex + 1} of ${n.steps.length}`);
      if (n.source === "route") {
        const share = n.distance > 0 ? left / n.distance : 0;
        const arrive = new Date(Date.now() + n.duration * share * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        setText(eta, `${arrive} · ${shortDuration(n.duration * share)} · ${fmtDistance(left)} to ${n.destination}`);
        map.set(n.line, n.distance > 0 ? 1 - left / n.distance : 0);
      } else {
        setText(eta, n.destination === "Navigation" ? "From your phone" : `${n.destination} · from your phone`);
        map.set([], 0);
      }
    },
  };
}

const RIDE_NODES: LiveIcon[] = ["user", "car", "pin", "flag"];
const DELIVERY_NODES: LiveIcon[] = ["store", "box", "truck", "home"];

/** A ride or an order: where it is on its way, and who brings it. */
function trackCard(brandId: string): Card {
  const brand = brandById(brandId);
  const ride = brand?.kind === "ride";
  const title = div("lv-title");
  const sub = div("lv-sub");
  const fill = div("lv-track-fill");
  const nodes = (ride ? RIDE_NODES : DELIVERY_NODES).map((n) => div("lv-node", icon(n, 15)));
  const track = div("lv-track", div("lv-track-line"), fill, ...nodes);
  const avatar = div("lv-avatar small");
  const who = div("lv-who");
  const otp = span("lv-otp");
  let id = "";
  const dismiss = roundBtn("x", "grey small", "Stop following", () => LiveCtl.dismiss(id), 15);
  const el = div("lv-card lv-trackcard",
    div("lv-row", div("lv-col grow", title, sub), brandTile(brandId, 34)),
    track,
    div("lv-row", avatar, who, div("grow"), otp, dismiss),
  );
  el.style.setProperty("--accent", brand?.color === "#FFFFFF" ? "#F5C518" : brand?.color ?? ORANGE);
  return {
    el,
    update(a) {
      if (!is(a, "ride") && !is(a, "delivery")) return;
      id = a.id;
      const d = a.data;
      const stages = is(a, "ride") ? RIDE_STAGES : DELIVERY_STAGES;
      const last = stages.length - 1;
      setText(title, stages[Math.min(d.stage, last)]);
      const done = d.stage >= last;
      setText(sub, done ? brand?.name ?? "" : d.eta ? `${/^\d/.test(d.eta) && d.eta.includes("min") ? "Arriving in" : "Estimated arrival"} ${d.eta}` : d.text.slice(0, 64));
      // A ride has five stages on four stops: finding and on-the-way share the first stretch.
      const position = is(a, "ride") ? [0.12, 1, 2, 2.5, 3][Math.min(d.stage, 4)] : d.stage;
      fill.style.setProperty("--p", String(position / 3));
      nodes.forEach((n, i) => n.classList.toggle("on", i <= position));
      const person = is(a, "ride") ? a.data.driver : a.data.courier;
      const extra = is(a, "ride") ? a.data.vehicle : "";
      avatar.style.display = who.style.display = person || extra ? "" : "none";
      setText(avatar, initials(person || brand?.name || "?"));
      setText(who, [person, extra].filter(Boolean).join(" · "));
      otp.style.display = d.otp && !done ? "" : "none";
      setText(otp, `${ride ? "PIN" : "OTP"} ${d.otp}`);
    },
  };
}

/** A colour for a team, always the same for the same name. */
function teamColor(abbr: string): string {
  let hash = 0;
  for (let i = 0; i < abbr.length; i++) hash = (hash * 31 + abbr.charCodeAt(i)) | 0;
  return `hsl(${Math.abs(hash) % 360} 62% 46%)`;
}

function sportsCard(): Card {
  const side = () => {
    const badge = div("lv-team-badge");
    const name = div("lv-team-name");
    const score = div("lv-team-score");
    return { badge, name, score };
  };
  const home = side();
  const away = side();
  const league = div("lv-sub center");
  const status = div("lv-match-status");
  const summary = div("lv-sub center lv-match-summary");
  let eventId = "";
  const remove = roundBtn("x", "grey small lv-corner", "Stop following this match", () => LiveCtl.hideMatch(eventId), 13);
  const el = div("lv-card lv-sports", remove,
    div("lv-row lv-scoreline",
      div("lv-team", home.badge, home.name), home.score,
      div("lv-col center grow", league, status),
      away.score, div("lv-team", away.badge, away.name)),
    summary,
  );
  const fill = (s: ReturnType<typeof side>, t: SportsData["home"], lost: boolean) => {
    setText(s.badge, t.abbr.slice(0, 4));
    s.badge.style.background = teamColor(t.abbr);
    setText(s.name, t.name);
    setText(s.score, shortScore(t.score));
    s.score.classList.toggle("dim", lost);
  };
  return {
    el,
    update(a) {
      if (!is(a, "sports")) return;
      const m = a.data;
      eventId = m.eventId;
      fill(home, m.home, m.state === "post" && m.away.winner);
      fill(away, m.away, m.state === "post" && m.home.winner);
      // Both scores in one size: the longer one decides.
      const long = Math.max(shortScore(m.home.score).length, shortScore(m.away.score).length) > 3;
      home.score.classList.toggle("long", long);
      away.score.classList.toggle("long", long);
      setText(league, m.league);
      status.classList.toggle("live", m.state === "in");
      const starts = m.startsAt ? new Date(m.startsAt).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
      setText(status, m.state === "in" ? `LIVE · ${m.status}` : m.state === "pre" ? starts || m.status : m.status || "Final");
      const detail = [m.home.score, m.away.score].some((s) => s.length > 8) ? `${m.home.abbr} ${m.home.score} · ${m.away.abbr} ${m.away.score}` : "";
      setText(summary, m.summary && m.summary !== m.status ? m.summary : detail);
    },
  };
}

/** The day's prices as a line, filled underneath, with yesterday's close dashed. */
function sparkline(): { el: HTMLElement; set(series: number[], prevClose: number, color: string): void } {
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = document.createElementNS(ns, "svg");
  svgEl.setAttribute("viewBox", "0 0 400 64");
  svgEl.setAttribute("preserveAspectRatio", "none");
  svgEl.innerHTML =
    '<defs><linearGradient id="lv-spark-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity="0.38"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>' +
    '<path class="lv-spark-area" fill="url(#lv-spark-fill)"/><line class="lv-spark-base" x1="0" x2="400"/><path class="lv-spark-line" fill="none"/>';
  const area = svgEl.querySelector(".lv-spark-area")!;
  const line = svgEl.querySelector(".lv-spark-line")!;
  const base = svgEl.querySelector(".lv-spark-base")!;
  const el = div("lv-spark", svgEl as unknown as Node);
  let key = "";
  return {
    el,
    set(series, prevClose, color) {
      const k = `${series.length}:${series[series.length - 1]}:${prevClose}:${color}`;
      if (k === key) return;
      key = k;
      el.style.color = color;
      el.classList.toggle("empty", series.length < 2);
      if (series.length < 2) return;
      const lo = Math.min(...series, prevClose || Infinity);
      const hi = Math.max(...series, prevClose || -Infinity);
      const range = hi - lo || 1;
      const x = (i: number) => (i / (series.length - 1)) * 400;
      const y = (v: number) => 4 + (1 - (v - lo) / range) * 52;
      const d = series.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
      line.setAttribute("d", d);
      area.setAttribute("d", `${d}L400,64L0,64Z`);
      const by = prevClose ? y(prevClose) : -10;
      base.setAttribute("y1", String(by));
      base.setAttribute("y2", String(by));
    },
  };
}

function stockCard(): Card {
  const symbol = div("lv-sub");
  const name = div("lv-title");
  const updated = div("lv-sub end");
  const price = span("lv-price");
  const change = span("lv-change");
  const pct = span("lv-change");
  const chart = sparkline();
  let sym = "";
  const remove = roundBtn("x", "grey small", "Stop watching", () => LiveCtl.unwatch(sym), 14);
  const el = div("lv-card lv-stock",
    div("lv-row", div("lv-col grow", symbol, name), div("lv-col end", div("lv-sub end", "updated"), updated), remove),
    div("lv-row baseline", price, div("lv-col", change, pct)),
    chart.el,
  );
  return {
    el,
    update(a, now) {
      if (!is(a, "stock")) return;
      const q = a.data;
      sym = q.symbol;
      const color = q.change >= 0 ? GREEN : RED;
      setText(symbol, q.symbol);
      setText(name, q.name);
      const mins = Math.floor((now - a.updatedAt) / 60_000);
      setText(updated, mins < 1 ? "just now" : `${mins}m ago`);
      setText(price, fmtMoney(q.price, q.currency));
      change.style.color = pct.style.color = color;
      setText(change, `${q.change >= 0 ? "+" : "−"}${fmtMoney(Math.abs(q.change), q.currency)}`);
      setText(pct, `${q.change >= 0 ? "▲" : "▼"} ${Math.abs(q.changePct).toFixed(2)}%${q.marketOpen ? "" : " · closed"}`);
      chart.set(q.series, q.prevClose, color);
    },
  };
}

function authCard(): Card {
  const glyph = div("lv-auth-glyph");
  const text = div("lv-auth-text");
  let shown = "";
  const el = div("lv-card lv-center lv-auth", glyph, text);
  return {
    el,
    update(a) {
      if (!is(a, "auth")) return;
      const d = a.data;
      const key = `${d.method}:${d.ok}`;
      if (key !== shown) {
        shown = key;
        clear(glyph);
        const base: LiveIcon = d.method === "face" ? "faceId" : d.method === "fingerprint" ? "fingerprint" : d.method === "password" ? "key" : d.ok === false || d.method === "lock" ? "lock" : "unlock";
        // The verdict replaces the glyph: a tick drawn in, or a shake.
        glyph.append(d.ok === true && (d.method === "face" || d.method === "fingerprint") ? div("lv-tick", icon("check", 40, 2.6)) : icon(base, 46, 1.7));
        el.dataset.state = d.ok == null ? "pending" : d.ok ? "ok" : "fail";
      }
      setText(text, d.detail || (d.ok == null ? "Checking…" : d.ok ? "Authenticated" : "Not recognised"));
    },
  };
}

function paymentCard(): Card {
  const amount = div("lv-pay-amount");
  const text = div("lv-sub center");
  const el = div("lv-card lv-center lv-pay", div("lv-tick ring", icon("check", 30, 2.8)), amount, text);
  return {
    el,
    update(a) {
      if (!is(a, "payment")) return;
      const p = a.data;
      setText(amount, `${p.direction === "received" ? "+" : ""}${fmtMoney(p.amount, p.currency)}`);
      const who = p.party ? `${p.direction === "received" ? "from" : "to"} ${p.party}` : "";
      setText(text, [p.direction === "received" ? "Received" : "Paid", who, p.app && !who ? `· ${p.app}` : ""].filter(Boolean).join(" "));
    },
  };
}

function deviceCard(): Card {
  const glyph = div("lv-device-glyph");
  const sub = div("lv-sub");
  const title = div("lv-title");
  const r = ring(46, 5);
  let shown = "";
  const el = div("lv-card lv-line", glyph, div("lv-col grow", sub, title), r.el);
  return {
    el,
    update(a) {
      if (!is(a, "device")) return;
      const d = a.data;
      if (shown !== d.type) {
        shown = d.type;
        clear(glyph);
        glyph.append(icon(d.type === "headphones" && /pods|buds/i.test(d.name) ? "earbuds" : deviceIcon(d.type), 28, 1.8));
      }
      setText(sub, d.percent != null && d.percent <= 15 ? "Battery low" : "Connected");
      setText(title, d.name);
      r.el.style.display = d.percent == null ? "none" : "";
      r.set((d.percent ?? 0) / 100, batteryColor(d.percent ?? 100, d.charging), d.percent != null ? String(d.percent) : "");
    },
  };
}

function batteryCard(): Card {
  const level = div("lv-batt-level");
  const body = div("lv-batt", level, div("lv-batt-cap"));
  const sub = div("lv-sub");
  const title = div("lv-title");
  const percent = span("lv-timer-time small");
  const el = div("lv-card lv-line", body, div("lv-col grow", sub, title), percent);
  return {
    el,
    update(a) {
      if (!is(a, "battery")) return;
      const b = a.data;
      const color = b.event === "low" ? RED : batteryColor(b.percent, b.charging);
      level.style.width = `${Math.max(6, b.percent)}%`;
      level.style.background = color;
      percent.style.color = color;
      setText(percent, `${b.percent}%`);
      setText(sub, "This computer");
      setText(title, { low: "Low Battery", charging: "Charging", full: "Fully charged", unplugged: "On battery" }[b.event]);
      el.classList.toggle("charging", b.charging);
    },
  };
}

function hotspotCard(): Card {
  const sub = div("lv-sub");
  const title = div("lv-title");
  const clients = span("lv-timer-time small green");
  const off = pill("Turn off", "ghost", () => LiveCtl.hotspotOff());
  const glyph = div("lv-device-glyph green", icon("link", 26, 2.2));
  const el = div("lv-card lv-line", glyph, div("lv-col grow", sub, title), clients, off);
  return {
    el,
    update(a) {
      if (!is(a, "hotspot")) return;
      setText(sub, "Personal Hotspot");
      setText(title, a.data.ssid);
      setText(clients, a.data.clients ? `${a.data.clients} connected` : "");
    },
  };
}

function cameraCard(_actions: ViewActions): Card {
  const title = div("lv-title");
  const sub = div("lv-sub");
  const el = div("lv-card lv-line", div("lv-device-glyph green", icon("camera", 26, 1.9)), div("lv-col grow", sub, title), div("lc-dot cam on big"));
  return {
    el,
    update(a) {
      if (!is(a, "camera")) return;
      setText(sub, "Camera in use");
      setText(title, a.data.apps.join(", ") || "Camera");
    },
  };
}

/** What the machine is doing, a row each: batteries, microphone, camera, screen, hotspot. */
export function buildStatusList(): { el: HTMLElement; sync(): void } {
  const rows = div("lv-status lv-scroll");
  let key = "";
  return {
    el: rows,
    sync() {
      const s = LiveCtl.system;
      const k = JSON.stringify(s);
      if (k === key) return;
      key = k;
      const row = (name: LiveIcon, color: string, label: string, value: string) => {
        const g = div("lv-status-glyph", icon(name, 15));
        g.style.color = color;
        return div("lv-status-row", g, span("lv-status-label", label), span("lv-status-value", value));
      };
      const out: HTMLElement[] = [];
      if (!s) out.push(span("lv-sub", "Waiting for the first report…"));
      else {
        if (s.battery.present) out.push(row(s.battery.charging ? "bolt" : "battery", batteryColor(s.battery.percent, s.battery.charging), "This computer", `${s.battery.percent}%${s.battery.charging ? " · charging" : s.battery.plugged ? " · plugged in" : ""}`));
        for (const d of s.devices) out.push(row(deviceIcon(d.kind), d.percent != null ? batteryColor(d.percent, d.charging) : "#fff", d.name, d.percent != null ? `${d.percent}%${d.charging ? " · charging" : ""}` : "Connected"));
        out.push(row("mic", s.mic.length ? ORANGE : "#6b7079", "Microphone", s.mic.length ? s.mic.join(", ") : "Not in use"));
        out.push(row("camera", s.camera.length ? GREEN : "#6b7079", "Camera", s.camera.length ? s.camera.join(", ") : "Not in use"));
        if (s.screen.length) out.push(row("record", RED, "Screen", "Recording"));
        out.push(row("link", s.hotspot ? GREEN : "#6b7079", "Hotspot", s.hotspot ? `${s.hotspot.ssid}${s.hotspot.clients ? ` · ${s.hotspot.clients} connected` : ""}` : "Off"));
      }
      rows.replaceChildren(...out);
    },
  };
}

/** The batteries this computer knows of (itself, earphones, the phone…), a glass pill each: ring, name, level. */
export function buildDeviceStrip(): { el: HTMLElement; sync(): void } {
  const el = div("dv");
  let key = "";
  return {
    el,
    sync() {
      const s = LiveCtl.system;
      const k = JSON.stringify(s && [s.battery, s.devices]);
      if (k === key) return;
      key = k;
      if (!s) {
        el.replaceChildren();
        return;
      }
      const items: { glyph: LiveIcon; name: string; percent: number | null; charging: boolean }[] = [];
      if (s.battery.present) items.push({ glyph: s.battery.charging || s.battery.plugged ? "bolt" : "battery", name: "This computer", percent: s.battery.percent, charging: s.battery.charging });
      for (const d of s.devices) {
        const glyph = d.kind === "headphones" && /pods|buds/i.test(d.name) ? "earbuds" : deviceIcon(d.kind);
        items.push({ glyph, name: d.name, percent: d.percent, charging: d.charging });
      }
      el.replaceChildren(...items.slice(0, 4).map((it) => {
        const r = ring(24, 2.5);
        r.set((it.percent ?? 0) / 100, it.percent == null ? "rgba(255,255,255,0.25)" : batteryColor(it.percent, it.charging));
        return h("div", { class: "dv-pill", title: `${it.name}${it.percent != null ? ` · ${it.percent}%` : ""}${it.charging ? " · charging" : ""}` },
          div("dv-ring", r.el, div("dv-glyph", icon(it.glyph, 11))),
          span("dv-name", it.name),
          span("dv-pct", it.percent != null ? `${it.percent}%` : "On"));
      }));
    },
  };
}

// ── The hub: start something, or see what the machine is doing ────────────────

type HubPanel = "tiles" | "timer" | "stocks" | "scores" | "navigate" | "status";

const HUB_SIZE: Record<HubPanel, { w: number; h: number }> = {
  tiles: { w: 316, h: 168 },
  timer: { w: W, h: 150 },
  stocks: { w: W, h: 176 },
  scores: { w: W, h: 232 },
  navigate: { w: W, h: 150 },
  status: { w: W, h: 196 },
};

function buildHub(actions: ViewActions, close: () => void): { el: HTMLElement; sync(): void; panel(): HubPanel; reset(): void; extra(): number } {
  let panel: HubPanel = "tiles";
  const body = div("lv-hub-body");
  const el = div("lv-card lv-hub", body);
  let built: HubPanel | null = null;
  let refresh: (() => void) | null = null;

  const go = (p: HubPanel) => {
    panel = p;
    LiveCtl.clearError();
    actions.blip();
    State.notify();
  };

  const field = (placeholder: string, onEnter: (value: string) => void): HTMLInputElement => {
    const input = h("input", { class: "lv-input", type: "text", placeholder, spellcheck: "false" });
    input.addEventListener("focus", () => { actions.keyboard(true); actions.holdOpen(true); });
    input.addEventListener("blur", () => { actions.keyboard(false); actions.holdOpen(false); });
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && input.value.trim()) {
        onEnter(input.value.trim());
        input.value = "";
      } else if (e.key === "Escape") {
        input.blur();
        go("tiles");
      }
    });
    input.addEventListener("mousedown", (e) => e.stopPropagation());
    // The window only takes the keyboard once it is asked to: then the caret lands.
    window.setTimeout(() => input.focus(), 140);
    return input;
  };

  const heading = (text: string) =>
    div("lv-hub-head", roundBtn("chevLeft", "grey small", "Back", () => go("tiles"), 15), span("lv-title", text));
  const error = () => {
    const e = div("lv-error");
    return { el: e, sync: () => setText(e, LiveCtl.error) };
  };
  const chip = (label: string, onRemove: () => void) =>
    h("button", { class: "lv-chip", title: "Remove", onclick: (e: Event) => { e.stopPropagation(); onRemove(); State.notify(); } }, label, icon("x", 10, 2.6));

  const tile = (name: LiveIcon, label: string, color: string, onClick: () => void) => {
    const glyph = div("lv-tile-glyph", icon(name, 20));
    glyph.style.color = color;
    return h("button", { class: "lv-tile", onclick: (e: Event) => { e.stopPropagation(); onClick(); } }, glyph, span("lv-tile-label", label));
  };

  const panels: Record<HubPanel, () => (() => void) | null> = {
    tiles() {
      // Unread messages, an app each: a click opens its chats.
      const unread = div("lv-unread");
      let unreadKey = "";
      const syncUnread = () => {
        const entries = Object.entries(State.cloveUnread).filter(([, n]) => n > 0);
        const key = entries.map(([a, n]) => `${a}:${n}`).join("|");
        if (key === unreadKey) return;
        unreadKey = key;
        unread.replaceChildren(...entries.map(([app, n]) => {
          const logo = APP_LOGOS[app];
          return h("button", { class: "lv-unread-chip", title: `Open ${app}`, onclick: (e: Event) => { e.stopPropagation(); openUnreadApp(app, actions); } },
            logo ? svg(logo, 13) : h("b", { text: app.slice(0, 1) }), span("lv-unread-name", app), span("lv-unread-count", n > 99 ? "99+" : String(n)));
        }));
        unread.style.display = entries.length ? "" : "none";
      };
      body.append(unread);
      body.append(div("lv-tiles",
        tile("mic", "Ask CLOVE", CLOVE, () => { close(); void LiveCtl.listen(); }),
        tile("timer", "Timer", ORANGE, () => go("timer")),
        tile("stopwatch", "Stopwatch", ORANGE, () => { LiveCtl.stopwatch("start"); close(); }),
        tile("wave", "Voice memo", RED, () => { void LiveCtl.memoStart().then(() => Live.get("memo") && close()); }),
        tile("pin", "Navigate", BLUE, () => go("navigate")),
        tile("chart", "Stocks", GREEN, () => go("stocks")),
        tile("trophy", "Scores", "#FFD60A", () => go("scores")),
        tile("activity", "Status", "#64D2FF", () => go("status")),
      ));
      const err = error();
      body.append(err.el);
      return () => {
        syncUnread();
        err.sync();
      };
    },
    timer() {
      const start = (seconds: number, label = "") => { LiveCtl.startTimer(seconds, label); close(); };
      const input = field("Custom: 25m, 1h 30m, 2:30, or “10m tea”", (v) => {
        const m = /^(.*?\d\s*(?:h(?:ou)?rs?|m(?:in(?:ute)?s?)?|s(?:ec(?:ond)?s?)?)?|\d+:\d\d(?::\d\d)?)\s*(.*)$/i.exec(v);
        const seconds = parseDuration(m?.[1] ?? v) ?? parseDuration(v);
        if (seconds) start(seconds, m?.[2] ?? "");
      });
      body.append(heading("Timer"),
        div("lv-presets", ...[1, 3, 5, 10, 15, 25, 45, 60].map((m) => pill(m < 60 ? `${m} min` : "1 hour", "ghost", () => start(m * 60)))),
        input);
      return null;
    },
    stocks() {
      const list = div("lv-chips");
      const err = error();
      const input = field("Add a symbol: TSLA, RELIANCE, NIFTY, BTC…", (v) => void LiveCtl.watch(v));
      body.append(heading("Stocks & markets"), input, list, err.el);
      let key = "";
      return () => {
        err.sync();
        const k = LiveCtl.prefs.watchlist.join("|");
        if (k === key) return;
        key = k;
        list.replaceChildren(...LiveCtl.prefs.watchlist.map((s) => chip(s, () => LiveCtl.unwatch(s))),
          ...(LiveCtl.prefs.watchlist.length ? [] : [span("lv-sub", "Nothing watched yet. Prices come from CNBC, about a minute behind.")]));
      };
    },
    scores() {
      const sports = div("lv-presets");
      const follows = div("lv-chips");
      const matches = div("lv-matches lv-scroll");
      const input = field("Follow a team or league: India, MI, Arsenal…", (v) => LiveCtl.follow(v));
      body.append(heading("Scores"), sports, input, follows, matches);
      void LiveCtl.refreshScores();
      let key = "";
      return () => {
        const p = LiveCtl.prefs;
        const k = `${p.sport}|${p.follows.join(",")}|${LiveCtl.matches.map((m) => m.eventId + m.home.score + m.away.score + m.state).join(",")}`;
        if (k === key) return;
        key = k;
        sports.replaceChildren(...SPORTS.map((s) => pill(s.name, s.id === p.sport ? "on" : "ghost", () => LiveCtl.setSport(s.id))));
        follows.replaceChildren(...p.follows.map((f) => chip(f, () => LiveCtl.unfollow(f))));
        const order = { in: 0, pre: 1, post: 2 };
        const top = [...LiveCtl.matches].sort((a, b) => order[a.state] - order[b.state]).slice(0, 3);
        matches.replaceChildren(...(top.length ? top.map((m) => h("button", {
          class: `lv-match ${m.state === "in" ? "live" : ""}`, title: "Follow this match",
          onclick: (e: Event) => { e.stopPropagation(); LiveCtl.follow(m.home.abbr); },
        }, span("lv-match-teams", `${m.home.abbr} ${shortScore(m.home.score)}  ·  ${m.away.abbr} ${shortScore(m.away.score)}`), span("lv-sub", m.state === "in" ? "LIVE" : m.status.slice(0, 22))))
          : [span("lv-sub", "No matches listed right now.")]));
      };
    },
    navigate() {
      const err = error();
      const busy = span("lv-sub");
      const input = field("Where to? “India Gate” or “Connaught Place from Noida”", (v) => {
        const m = /^(.*?)\s+from\s+(.+)$/i.exec(v);
        setText(busy, "Finding the route…");
        void LiveCtl.navigate(m ? m[1] : v, m ? m[2] : "").then((ok) => {
          setText(busy, "");
          if (ok) close();
        });
      });
      const home = LiveCtl.prefs.home;
      body.append(heading("Navigate"), input,
        div("lv-row", span("lv-sub", home ? `Starts from ${home.name}.` : "Starts from your network's city unless you add “from …”."), busy), err.el);
      return err.sync;
    },
    status() {
      const list = buildStatusList();
      body.append(heading("Status"), list.el);
      return list.sync;
    },
  };

  return {
    el,
    panel: () => panel,
    /** Height beyond the panel's own: the row of unread messages over the tiles. */
    extra: () => (panel === "tiles" && Object.values(State.cloveUnread).some((n) => n > 0) ? 34 : 0),
    reset() {
      panel = "tiles";
    },
    sync() {
      if (built !== panel) {
        built = panel;
        clear(body);
        body.dataset.panel = panel;
        refresh = panels[panel]();
      }
      refresh?.();
    },
  };
}

// ── The view ──────────────────────────────────────────────────────────────────

export interface LiveView extends ViewHost {
  /** The island's size for what the view shows now. */
  size(): { w: number; h: number };
  /** A banner shows the card alone: no dock, nothing to navigate. */
  setBanner(on: boolean): void;
  readonly banner: boolean;
  /** Opens on the launcher instead of an activity. */
  openHub(): void;
  /** The island folded or left the live view: the next click on a card is a first one again. */
  resetClicks(): void;
  /** The launcher is on screen rather than an activity's card. */
  readonly hubShown: boolean;
}

const DOCK_H = 38;

export function buildLive(actions: ViewActions): LiveView {
  const stage = div("lv-stage");
  const dock = div("lv-dock");
  const el = h("div", { class: "view live-view" }, stage, dock);
  let banner = false;
  let hubOpen = false;
  let cardKey = "";
  let card: Card | null = null;
  let dockKey = "";
  const hub = buildHub(actions, () => {
    hubOpen = false;
    hub.reset();
    State.notify();
  });

  const focused = () => Live.focused(Date.now()) as AnyActivity | null;

  // A click on the card itself (not on one of its buttons) opens what it is about, but never the first
  // one: a card that came up by itself (a score, a price) or was just opened is only kept open by it.
  // `clicks` starts again with every card and every time the island opens.
  let clicks = 0;
  stage.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("button, input, .lv-bar, .lv-hub") || State.mode !== "expanded") return;
    const a = showsHub() ? null : focused();
    if (!a || !(linkOf(a) || a.kind === "media" || a.kind === "call")) return;
    if (++clicks < 2) {
      stage.title = "Click again to open";
      return;
    }
    if (LiveCtl.open(a.id)) actions.blip();
  });

  // The wheel goes through the activities, as a swipe would.
  let wheeled = 0;
  el.addEventListener("wheel", (e) => {
    if ((e.target as HTMLElement).closest(".lv-scroll")) return;
    e.preventDefault();
    const now = Date.now();
    if (now - wheeled < 260 || Math.abs(e.deltaY) + Math.abs(e.deltaX) < 4 || showsHub()) return;
    const list = Live.ranked(now);
    if (list.length < 2) return;
    wheeled = now;
    const at = Math.max(0, list.findIndex((a) => a.id === focused()?.id));
    const step = e.deltaY + e.deltaX > 0 ? 1 : -1;
    Live.focusId = list[(at + step + list.length) % list.length].id;
    actions.blip();
    State.notify();
  }, { passive: false });
  const showsHub = () => hubOpen || Live.size === 0;
  const showsDock = () => !banner;

  function syncDock(now: number) {
    dock.style.display = showsDock() ? "" : "none";
    if (!showsDock()) return;
    const list = Live.ranked(now);
    const current = showsHub() ? "" : focused()?.id ?? "";
    const key = `${list.map((a) => `${a.id}:${accentOf(a)}`).join("|")}#${current}#${hubOpen}`;
    if (key === dockKey) return;
    dockKey = key;
    const chips = list.slice(0, 8).map((a) => {
      const b = h("button", {
        class: `lv-dock-chip ${a.id === current ? "on" : ""}`, title: titleOf(a),
        onclick: (e: Event) => {
          e.stopPropagation();
          Live.focusId = a.id;
          hubOpen = false;
          actions.blip();
          State.notify();
        },
      }, is(a, "ride") || is(a, "delivery") ? brandTile(a.data.brand, 16) : icon(KIND_ICON[a.kind], 14));
      b.style.color = accentOf(a);
      return b;
    });
    const add = h("button", {
      class: `lv-dock-chip plain ${showsHub() ? "on" : ""}`, title: "Start something",
      onclick: (e: Event) => {
        e.stopPropagation();
        hubOpen = !hubOpen || Live.size === 0;
        hub.reset();
        actions.blip();
        State.notify();
      },
    }, icon("plus", 14, 2.4));
    dock.replaceChildren(div("lv-dock-group", ...chips), div("lv-dock-group", add));
  }

  return {
    el,
    get banner() {
      return banner;
    },
    get hubShown() {
      return showsHub();
    },
    setBanner(on) {
      banner = on;
      clicks = 0;
      if (on) hubOpen = false;
    },
    resetClicks() {
      if (clicks === 0) return;
      clicks = 0;
      stage.title = "";
    },
    openHub() {
      hubOpen = true;
      hub.reset();
    },
    size() {
      const a = showsHub() ? null : focused();
      const base = a ? cardSize(a) : HUB_SIZE[hub.panel()];
      return { w: base.w, h: base.h + (a ? 0 : hub.extra()) + (showsDock() ? DOCK_H : 0) };
    },
    sync() {
      const now = Date.now();
      const a = showsHub() ? null : focused();
      const key = a ? `${a.id}|${a.kind}|${is(a, "ride") || is(a, "delivery") ? a.data.brand : ""}` : "hub";
      if (key !== cardKey) {
        cardKey = key;
        clicks = 0;
        stage.title = "";
        card = a ? buildCard(a, actions) : null;
        const next = card?.el ?? hub.el;
        next.classList.remove("enter");
        stage.replaceChildren(next);
        void next.offsetWidth;
        next.classList.add("enter");
      }
      if (a) card?.update(a, now);
      else hub.sync();
      stage.classList.toggle("linked", a != null && (linkOf(a) != null || a.kind === "media" || a.kind === "call"));
      syncDock(now);
    },
  };
}

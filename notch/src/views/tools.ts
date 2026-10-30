// CLOVE fork: two pages in the style of the overview — two cards side by side.
//
//   Controls:  [ music: cover, title, artist, bar, ⏮ ⏯ ⏭ ]  [ screenshot · record · stay awake · night light ]
//                                                         [ timer | stopwatch | alarm                        ]
//   Time:      [ today, big · the month                  ]  [ the world in dots, day and night · city clocks  ]

import { State } from "../core/state";
import {
  Tools, cityTime, clockText, isDay, subsolarPoint, type ClockTab,
} from "../core/tools";
import { N_, t, tl } from "../i18n/i18n";
import { MAP_COLS, MAP_ROWS, MAP_STEP, MAP_TOP_LAT, isLand } from "./worldmask";
import { clear, h, svg } from "./dom";
import { ICONS } from "./icons";
import type { ViewHost } from "./views";

function card(...children: (Node | string)[]): HTMLElement {
  return h("div", { class: "card" }, ...children);
}

function iconBtn(cls: string, title: string, icon: string, onClick: () => void, size = 14, stroke = 0): HTMLButtonElement {
  return h("button", {
    class: cls, title: tl(title),
    onclick: (e: Event) => { e.stopPropagation(); onClick(); },
  }, svg(icon, size, stroke ? { stroke } : {})) as HTMLButtonElement;
}

// ── Controls ──────────────────────────────────────────────────────────────────

export function buildControls(): ViewHost {
  // Music
  const art = h("div", { class: "mp-art" });
  const glow = h("div", { class: "mp-glow" });
  const title = h("div", { class: "mp-title" });
  const artist = h("div", { class: "mp-artist" });
  const player = h("div", { class: "mp-player" });
  const bar = h("div", { class: "mp-bar" }, h("i"));
  const pos = h("span", { class: "mp-time" });
  const len = h("span", { class: "mp-time" });
  const playBtn = iconBtn("mp-btn play", N_("Play or pause"), ICONS.play, () => void Tools.mediaControl("toggle"), 16);
  const music = card(
    glow,
    h("div", { class: "mp" },
      h("div", { class: "mp-top" }, art,
        h("div", { class: "mp-text" }, player, title, artist,
          h("div", { class: "mp-controls" },
            iconBtn("mp-btn", N_("Previous"), ICONS.backward, () => void Tools.mediaControl("previous"), 13),
            playBtn,
            iconBtn("mp-btn", N_("Next"), ICONS.forward, () => void Tools.mediaControl("next"), 13)))),
      h("div", { class: "mp-progress" }, pos, bar, len)),
  );

  // Quick tiles
  type TileId = "screenshot" | "record" | "awake" | "nightlight";
  const tileDefs: { id: TileId; label: string; icon: string }[] = [
    { id: "screenshot", label: N_("Screenshot"), icon: ICONS.camera },
    { id: "record", label: N_("Record"), icon: ICONS.recordScreen },
    { id: "awake", label: N_("Stay awake"), icon: ICONS.coffee },
    { id: "nightlight", label: N_("Night light"), icon: ICONS.moon },
  ];
  const tiles = new Map<TileId, { el: HTMLElement; sub: HTMLElement }>();
  const tileRow = h("div", { class: "qt-row" });
  for (const d of tileDefs) {
    const sub = h("span", { class: "qt-sub" });
    const el = h("button", {
      class: `qt qt-${d.id}`, title: tl(d.label),
      onclick: (e: Event) => {
        e.stopPropagation();
        if (d.id === "screenshot") {
          el.classList.add("flash");
          window.setTimeout(() => el.classList.remove("flash"), 450);
          // Out of the way first, so the shot is of the screen, not of Clove Notch.
          window.dispatchEvent(new CustomEvent("clove-fold"));
          window.setTimeout(() => void Tools.act("screenshot"), 350);
        } else if (d.id === "record" && !Tools.status.recording) {
          window.dispatchEvent(new CustomEvent("clove-fold"));
          window.setTimeout(() => void Tools.act("record"), 350);
        } else {
          void Tools.act(d.id);
        }
      },
    }, svg(d.icon, 18, { stroke: 1.8 }), h("span", { class: "qt-label", text: t(d.label) }), sub);
    tiles.set(d.id, { el, sub });
    tileRow.append(el);
  }

  // Timer / stopwatch / alarm
  const segs = new Map<ClockTab, HTMLElement>();
  const seg = h("div", { class: "ck-seg" });
  const segDefs: { id: ClockTab; title: string; icon: string }[] = [
    { id: "timer", title: N_("Timer"), icon: ICONS.hourglass },
    { id: "stopwatch", title: N_("Stopwatch"), icon: ICONS.stopwatch },
    { id: "alarm", title: N_("Alarm"), icon: ICONS.bell },
  ];
  for (const d of segDefs) {
    const b = iconBtn("ck-tab", d.title, d.icon, () => { Tools.clockTab = d.id; }, 12, 1.8);
    segs.set(d.id, b);
    seg.append(b);
  }
  const digits = h("div", { class: "ck-digits" });
  const caption = h("div", { class: "ck-caption" });
  const mainBtn = h("button", { class: "ck-btn primary" }) as HTMLButtonElement;
  const sideBtn = h("button", { class: "ck-btn" }) as HTMLButtonElement;
  // Alarm being set: its hour and minute, changed by a click (or the wheel) on each half of the digits.
  let draftH = 7;
  let draftM = 0;
  const hourEl = h("span", { class: "ck-part" });
  const minEl = h("span", { class: "ck-part" });
  const step = (part: "h" | "m", dir: number) => {
    if (part === "h") draftH = (draftH + dir + 24) % 24;
    else draftM = (draftM + dir * 5 + 60) % 60;
    State.notify();
  };
  hourEl.addEventListener("click", (e) => { e.stopPropagation(); step("h", 1); });
  minEl.addEventListener("click", (e) => { e.stopPropagation(); step("m", 1); });
  hourEl.addEventListener("wheel", (e) => { e.preventDefault(); step("h", e.deltaY < 0 ? 1 : -1); }, { passive: false });
  minEl.addEventListener("wheel", (e) => { e.preventDefault(); step("m", e.deltaY < 0 ? 1 : -1); }, { passive: false });
  // The timer's set time changes with the wheel too, a minute a notch.
  digits.addEventListener("wheel", (e) => {
    if (Tools.clockTab !== "timer" || Tools.timerRunning) return;
    e.preventDefault();
    Tools.timerAdd(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  mainBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (Tools.ringing) return Tools.stopRinging();
    if (Tools.clockTab === "timer") Tools.timerToggle();
    else if (Tools.clockTab === "stopwatch") Tools.stopwatchToggle();
    else Tools.addAlarm(draftH, draftM);
  });
  sideBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (Tools.clockTab === "timer") {
      if (Tools.timerIdle) Tools.timerAdd(1);
      else Tools.timerReset();
    } else if (Tools.clockTab === "stopwatch") Tools.stopwatchLapOrReset();
    else {
      const next = Tools.nextAlarm();
      if (next) Tools.removeAlarm(next.alarm.id);
    }
  });
  const clock = h("div", { class: "ck" }, seg, h("div", { class: "ck-mid" }, digits, caption), h("div", { class: "ck-btns" }, sideBtn, mainBtn));

  const right = card(h("div", { class: "ctl-right" }, tileRow, clock));
  const el = h("div", { class: "view overview tools-view" }, h("div", { class: "left" }, music), h("div", { class: "right" }, right));

  let artKey = "";
  let digitsKey = "";

  function setBtn(b: HTMLButtonElement, icon: string, label: string, stroke = 0) {
    const key = `${icon}|${label}`;
    if (b.dataset.key === key) return;
    b.dataset.key = key;
    b.title = t(label);
    clear(b);
    b.append(svg(icon, 12, stroke ? { stroke } : {}));
  }

  function syncClock() {
    const tab = Tools.clockTab;
    segs.forEach((b, id) => b.classList.toggle("on", id === tab));
    const now = Date.now();
    clock.classList.toggle("ringing", Tools.ringing != null);
    if (Tools.ringing) {
      digits.textContent = Tools.ringing.kind === "timer" ? "0:00" : Tools.ringing.label;
      digitsKey = "";
      caption.textContent = Tools.ringing.kind === "timer" ? t("Time's up") : t("Alarm");
      setBtn(mainBtn, ICONS.xmark, N_("Stop"));
      sideBtn.hidden = true;
      return;
    }
    sideBtn.hidden = false;
    if (tab === "timer") {
      digits.textContent = clockText(Tools.timerLeft(now));
      digitsKey = "";
      const running = Tools.timerRunning;
      caption.textContent = running ? t("Running") : Tools.timerIdle ? t("Scroll to set") : t("Paused");
      setBtn(mainBtn, running ? ICONS.pause : ICONS.play, running ? N_("Pause") : N_("Start"));
      setBtn(sideBtn, Tools.timerIdle ? ICONS.plus : ICONS.arrowClockwise, Tools.timerIdle ? N_("One more minute") : N_("Reset"), Tools.timerIdle ? 0 : 2);
      clock.classList.toggle("live", running);
    } else if (tab === "stopwatch") {
      digits.textContent = clockText(Tools.stopwatchMs(now), true);
      digitsKey = "";
      const running = Tools.stopwatchRunning;
      const laps = Tools.laps;
      caption.textContent = laps.length ? t("Lap {0} · {1}", { 0: laps.length, 1: clockText(laps[0] - (laps[1] ?? 0), true) }) : running ? t("Running") : "";
      setBtn(mainBtn, running ? ICONS.pause : ICONS.play, running ? N_("Pause") : N_("Start"));
      setBtn(sideBtn, running ? ICONS.flag : ICONS.arrowClockwise, running ? N_("Lap") : N_("Reset"), 2);
      clock.classList.toggle("live", running);
    } else {
      const key = `${draftH}:${draftM}`;
      if (key !== digitsKey) {
        digitsKey = key;
        hourEl.textContent = String(draftH).padStart(2, "0");
        minEl.textContent = String(draftM).padStart(2, "0");
        clear(digits);
        digits.append(hourEl, h("span", { class: "ck-colon", text: ":" }), minEl);
      }
      const next = Tools.nextAlarm();
      const on = Tools.alarms.filter((a) => a.on).length;
      caption.textContent = next
        ? t("Next {0} · in {1}", {
          0: `${String(next.alarm.h).padStart(2, "0")}:${String(next.alarm.m).padStart(2, "0")}`,
          1: next.inMin >= 60 ? `${Math.floor(next.inMin / 60)} h ${next.inMin % 60} min` : `${next.inMin} min`,
        }) + (on > 1 ? ` · +${on - 1}` : "")
        : t("Click to set");
      setBtn(mainBtn, ICONS.plus, N_("Add alarm"));
      setBtn(sideBtn, ICONS.xmark, N_("Remove the next alarm"));
      sideBtn.disabled = next == null;
      clock.classList.remove("live");
    }
  }

  function syncMusic() {
    const m = Tools.media;
    music.classList.toggle("empty", !m);
    if (!m) {
      player.textContent = t("Music");
      title.textContent = t("Nothing playing");
      artist.textContent = t("Play something and it shows here.");
      if (artKey !== "") {
        artKey = "";
        clear(art);
        glow.style.backgroundImage = "";
      }
      if (!art.firstChild) art.append(svg(ICONS.musicNote, 22));
      pos.textContent = "";
      len.textContent = "";
      (bar.firstChild as HTMLElement).style.width = "0%";
      return;
    }
    player.textContent = m.player;
    title.textContent = m.title;
    artist.textContent = m.artist;
    if (m.art !== artKey) {
      artKey = m.art;
      clear(art);
      if (m.art) {
        art.append(h("img", { src: m.art, alt: "" }));
        glow.style.backgroundImage = `url("${m.art}")`;
      } else {
        art.append(svg(ICONS.musicNote, 22));
        glow.style.backgroundImage = "";
      }
    }
    const p = Tools.mediaPosition();
    pos.textContent = m.length ? clockText(p * 1000) : "";
    len.textContent = m.length ? clockText(m.length * 1000) : "";
    (bar.firstChild as HTMLElement).style.width = m.length ? `${Math.min(100, (p / m.length) * 100)}%` : "0%";
    playBtn.classList.toggle("playing", m.playing);
    const key = m.playing ? "pause" : "play";
    if (playBtn.dataset.key !== key) {
      playBtn.dataset.key = key;
      clear(playBtn);
      playBtn.append(svg(m.playing ? ICONS.pause : ICONS.play, 16));
    }
    music.classList.toggle("playing", m.playing);
  }

  function syncTiles() {
    const s = Tools.status;
    tiles.get("awake")!.el.classList.toggle("on", s.awake);
    tiles.get("nightlight")!.el.classList.toggle("on", s.nightlight);
    const rec = tiles.get("record")!;
    rec.el.classList.toggle("on", s.recording);
    rec.sub.textContent = s.recording && Tools.recordingSince ? clockText(Date.now() - Tools.recordingSince) : "";
    rec.el.title = s.recording ? t("Stop recording") : t("Record");
  }

  return {
    el,
    sync() {
      if (State.view !== "controls") return;
      syncMusic();
      syncTiles();
      syncClock();
    },
  };
}

// ── Time ──────────────────────────────────────────────────────────────────────

/** The city he is in: the first whose clock reads the same as this PC's (zone names vary: Asia/Calcutta, Asia/Kolkata). */
function hereCity(now: Date) {
  return Tools.cities.slice(0, 4).find((c) => cityTime(c.zone, now).offset === "") ?? null;
}

export function buildTime(): ViewHost {
  const bigDay = h("div", { class: "cal-day" });
  const bigWeekday = h("div", { class: "cal-weekday" });
  const bigMonth = h("div", { class: "cal-month" });
  const nextAlarm = h("div", { class: "cal-alarm" });
  const monthTitle = h("div", { class: "cal-title" });
  const grid = h("div", { class: "cal-grid" });
  let shown = new Date();
  shown = new Date(shown.getFullYear(), shown.getMonth(), 1);
  const move = (d: number) => {
    shown = new Date(shown.getFullYear(), shown.getMonth() + d, 1);
    calKey = "";
    State.notify();
  };
  const calendar = card(h("div", { class: "cal" },
    h("div", { class: "cal-today" }, bigWeekday, bigDay, bigMonth, nextAlarm),
    h("div", { class: "cal-side" },
      h("div", { class: "cal-head" },
        iconBtn("cal-nav", N_("Previous month"), ICONS.chevronLeft, () => move(-1), 10, 2.2),
        monthTitle,
        iconBtn("cal-nav", N_("Next month"), ICONS.chevronRight, () => move(1), 10, 2.2)),
      grid)));
  monthTitle.addEventListener("click", (e) => {
    e.stopPropagation();
    const n = new Date();
    shown = new Date(n.getFullYear(), n.getMonth(), 1);
    calKey = "";
    State.notify();
  });

  // The world
  const canvas = h("canvas", { class: "wm-canvas" }) as HTMLCanvasElement;
  const cities = h("div", { class: "wm-cities" });
  const world = card(h("div", { class: "wm" }, canvas, cities));

  const el = h("div", { class: "view overview tools-view" }, h("div", { class: "left" }, calendar), h("div", { class: "right" }, world));

  let calKey = "";
  let mapKey = "";
  let cityKey = "";

  function syncCalendar(now: Date) {
    const lang = document.documentElement.lang || undefined;
    const key = `${now.toDateString()}~${shown.getTime()}~${lang}`;
    const next = Tools.nextAlarm(now);
    nextAlarm.textContent = next ? `⏰ ${String(next.alarm.h).padStart(2, "0")}:${String(next.alarm.m).padStart(2, "0")}` : "";
    if (key === calKey) return;
    calKey = key;
    bigDay.textContent = String(now.getDate());
    bigWeekday.textContent = now.toLocaleDateString(lang, { weekday: "long" });
    bigMonth.textContent = now.toLocaleDateString(lang, { month: "long", year: "numeric" });
    monthTitle.textContent = shown.toLocaleDateString(lang, { month: "short", year: "numeric" });
    clear(grid);
    // Weeks start on Monday.
    for (let i = 0; i < 7; i++) {
      const d = new Date(2024, 0, 1 + i);           // 1 Jan 2024 was a Monday
      grid.append(h("span", { class: "cal-dow", text: d.toLocaleDateString(lang, { weekday: "narrow" }) }));
    }
    const first = (shown.getDay() + 6) % 7;
    const days = new Date(shown.getFullYear(), shown.getMonth() + 1, 0).getDate();
    for (let i = 0; i < first; i++) grid.append(h("span"));
    for (let d = 1; d <= days; d++) {
      const today = shown.getFullYear() === now.getFullYear() && shown.getMonth() === now.getMonth() && d === now.getDate();
      const dow = (first + d - 1) % 7;
      grid.append(h("span", { class: `cal-d${today ? " today" : ""}${dow >= 5 ? " weekend" : ""}`, text: String(d) }));
    }
  }

  function syncWorld(now: Date) {
    const key = `${Math.floor(now.getTime() / 60_000)}`;
    if (key !== mapKey) {
      mapKey = key;
      drawMap(now);
    }
    const ck = `${now.getHours()}:${now.getMinutes()}`;
    if (ck === cityKey) return;
    cityKey = ck;
    clear(cities);
    const here = hereCity(now);
    const sun = subsolarPoint(now);
    for (const c of Tools.cities.slice(0, 4)) {
      const ct = cityTime(c.zone, now);
      const day = isDay(c.lat, c.lon, sun);
      cities.append(h("div", { class: `wm-city${c === here ? " here" : ""}` },
        h("span", { class: "wm-name" }, svg(day ? ICONS.sun : ICONS.moon, 8, { stroke: 2 }), h("b", { text: c.name })),
        h("span", { class: "wm-time", text: ct.time }),
        h("span", { class: "wm-off", text: c === here ? t("Here") : ct.offset })));
    }
  }

  function drawMap(now: Date) {
    const cssW = canvas.clientWidth || 260;
    const cssH = canvas.clientHeight || 98;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, cssW, cssH);
    const pitch = Math.min(cssW / MAP_COLS, cssH / MAP_ROWS);
    const ox = (cssW - pitch * MAP_COLS) / 2;
    const oy = (cssH - pitch * MAP_ROWS) / 2;
    const sun = subsolarPoint(now);
    const r = Math.max(0.8, pitch * 0.36);
    for (let row = 0; row < MAP_ROWS; row++) {
      const lat = MAP_TOP_LAT - MAP_STEP * row - MAP_STEP / 2;
      for (let col = 0; col < MAP_COLS; col++) {
        if (!isLand(col, row)) continue;
        const lon = -180 + MAP_STEP * col + MAP_STEP / 2;
        g.fillStyle = isDay(lat, lon, sun) ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.13)";
        g.beginPath();
        g.arc(ox + col * pitch + pitch / 2, oy + row * pitch + pitch / 2, r, 0, Math.PI * 2);
        g.fill();
      }
    }
    // The cities: a dot each, the one he is in brighter, with a soft ring.
    const here = hereCity(now);
    const xy = (lat: number, lon: number) => ({
      x: ox + ((lon + 180) / MAP_STEP) * pitch,
      y: oy + ((MAP_TOP_LAT - lat) / MAP_STEP) * pitch,
    });
    for (const c of Tools.cities.slice(0, 4)) {
      const p = xy(c.lat, c.lon);
      const mine = c === here;
      g.fillStyle = mine ? "rgba(52,211,153,0.25)" : "rgba(255,180,84,0.22)";
      g.beginPath();
      g.arc(p.x, p.y, mine ? 6 : 5, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = mine ? "#34D399" : "#FFB454";
      g.beginPath();
      g.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
      g.fill();
    }
    // Where the sun is overhead.
    const s = xy(sun.lat, sun.lon);
    const grad = g.createRadialGradient(s.x, s.y, 0, s.x, s.y, 14);
    grad.addColorStop(0, "rgba(255,214,102,0.55)");
    grad.addColorStop(1, "rgba(255,214,102,0)");
    g.fillStyle = grad;
    g.beginPath();
    g.arc(s.x, s.y, 14, 0, Math.PI * 2);
    g.fill();
  }

  return {
    el,
    sync() {
      if (State.view !== "time") return;
      const now = new Date();
      syncCalendar(now);
      syncWorld(now);
    },
  };
}

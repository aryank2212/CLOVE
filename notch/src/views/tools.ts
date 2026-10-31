// CLOVE fork: two pages in the style of the overview — two cards side by side.
//
//   Controls:  [ music: cover, title, artist, bar, ⏮ ⏯ ⏭ ]  [ screenshot · record · stay awake · night light ]
//                                                         [ timer | stopwatch | alarm                        ]
//   Time:      [ today, big · the month                  ]  [ the world in dots, day and night · city clocks  ]

import { State } from "../core/state";
import {
  Tools, cityTime, clockText, isDay, nearestCity, subsolarPoint, type ClockTab,
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
  const playBtn = iconBtn("mp-btn play", N_("Play or pause"), ICONS.play, () => void Tools.mediaControl("toggle"), 15);
  const openBtn = iconBtn("mp-open", N_("Open Apple Music in Chrome"), ICONS.openOut, () => Tools.openAppleMusic(), 13, 2);
  const music = card(
    glow,
    h("div", { class: "mp" },
      h("div", { class: "mp-top" }, art, h("div", { class: "mp-text" }, player, title, artist), openBtn),
      h("div", { class: "mp-bottom" },
        h("div", { class: "mp-controls" },
          iconBtn("mp-btn", N_("Previous"), ICONS.backward, () => void Tools.mediaControl("previous"), 13),
          playBtn,
          iconBtn("mp-btn", N_("Next"), ICONS.forward, () => void Tools.mediaControl("next"), 13)),
        h("div", { class: "mp-progress" }, pos, bar, len))),
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
      playBtn.append(svg(m.playing ? ICONS.pause : ICONS.play, 15));
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
  return Tools.cities.find((c) => cityTime(c.zone, now).offset === "") ?? null;
}

const DAY_MS = 86_400_000;

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function buildTime(): ViewHost {
  // ── The calendar: a click on a day shows it on the left; the wheel or the arrows change the month ──
  const bigDay = h("div", { class: "cal-day" });
  const bigWeekday = h("div", { class: "cal-weekday" });
  const bigMonth = h("div", { class: "cal-month" });
  const relative = h("div", { class: "cal-rel" });
  const nextAlarm = h("div", { class: "cal-alarm" });
  const monthTitle = h("div", { class: "cal-title" });
  const todayBtn = h("button", { class: "cal-todaybtn", text: t("Today") }) as HTMLButtonElement;
  const grid = h("div", { class: "cal-grid" });
  let shown = new Date();
  shown = new Date(shown.getFullYear(), shown.getMonth(), 1);
  let picked: Date | null = null;
  const move = (d: number) => {
    shown = new Date(shown.getFullYear(), shown.getMonth() + d, 1);
    calKey = "";
    State.notify();
  };
  const toToday = () => {
    const n = new Date();
    shown = new Date(n.getFullYear(), n.getMonth(), 1);
    picked = null;
    calKey = "";
    State.notify();
  };
  todayBtn.addEventListener("click", (e) => { e.stopPropagation(); toToday(); });
  monthTitle.addEventListener("click", (e) => { e.stopPropagation(); toToday(); });
  grid.addEventListener("wheel", (e) => { e.preventDefault(); move(e.deltaY > 0 ? 1 : -1); }, { passive: false });
  grid.addEventListener("click", (e) => {
    const cell = (e.target as HTMLElement).closest<HTMLElement>(".cal-d");
    if (!cell?.dataset.day) return;
    e.stopPropagation();
    const d = new Date(shown.getFullYear(), shown.getMonth(), Number(cell.dataset.day));
    picked = picked && sameDay(picked, d) ? null : d;
    calKey = "";
    State.notify();
  });
  const calendar = card(h("div", { class: "cal" },
    h("div", { class: "cal-today" }, bigWeekday, bigDay, bigMonth, relative, nextAlarm),
    h("div", { class: "cal-side" },
      h("div", { class: "cal-head" },
        iconBtn("cal-nav", N_("Previous month"), ICONS.chevronLeft, () => move(-1), 10, 2.2),
        monthTitle,
        todayBtn,
        iconBtn("cal-nav", N_("Next month"), ICONS.chevronRight, () => move(1), 10, 2.2)),
      grid)));

  // ── The world: hover for the time anywhere; click a city clock, then the map, to change it; wheel to cycle ──
  const canvas = h("canvas", { class: "wm-canvas" }) as HTMLCanvasElement;
  const tip = h("div", { class: "wm-tip", hidden: true });
  const hint = h("div", { class: "wm-hint", hidden: true, text: t("Click the map to choose a city") });
  const cities = h("div", { class: "wm-cities" });
  const mapBox = h("div", { class: "wm-map" }, canvas, tip, hint);
  const world = card(h("div", { class: "wm" }, mapBox, cities));
  let picking: number | null = null;
  let geo = { ox: 0, oy: 0, pitch: 1 };

  const latLonAt = (e: MouseEvent) => {
    const r = canvas.getBoundingClientRect();
    const scale = r.width / (canvas.clientWidth || r.width);
    const x = (e.clientX - r.left) / scale;
    const y = (e.clientY - r.top) / scale;
    const lon = ((x - geo.ox) / geo.pitch) * MAP_STEP - 180;
    const lat = MAP_TOP_LAT - ((y - geo.oy) / geo.pitch) * MAP_STEP;
    return { x, y, lat: Math.max(-60, Math.min(80, lat)), lon: Math.max(-180, Math.min(180, lon)) };
  };
  canvas.addEventListener("mousemove", (e) => {
    const p = latLonAt(e);
    const c = nearestCity(p.lat, p.lon);
    tip.hidden = false;
    tip.textContent = `${c.name} · ${cityTime(c.zone).time}`;
    tip.style.left = `${Math.min(Math.max(p.x, 40), (canvas.clientWidth || 260) - 40)}px`;
    tip.style.top = `${Math.max(p.y - 6, 10)}px`;
  });
  canvas.addEventListener("mouseleave", () => { tip.hidden = true; });
  canvas.addEventListener("click", (e) => {
    e.stopPropagation();
    if (picking == null) {
      // No city clock picked yet: say how.
      hint.textContent = t("Click a city below first, then the map");
      hint.hidden = false;
      window.setTimeout(() => {
        if (picking == null) hint.hidden = true;
        hint.textContent = t("Click the map to choose a city");
      }, 2200);
      return;
    }
    const p = latLonAt(e);
    Tools.setCity(picking, nearestCity(p.lat, p.lon));
    picking = null;
    hint.hidden = true;
    cityKey = "";
    mapKey = "";
  });

  const el = h("div", { class: "view overview tools-view" }, h("div", { class: "left" }, calendar), h("div", { class: "right" }, world));

  let calKey = "";
  let mapKey = "";
  let cityKey = "";

  function syncCalendar(now: Date) {
    const lang = document.documentElement.lang || undefined;
    const key = `${now.toDateString()}~${shown.getTime()}~${picked?.getTime() ?? 0}~${lang}`;
    const next = Tools.nextAlarm(now);
    nextAlarm.textContent = next ? `⏰ ${String(next.alarm.h).padStart(2, "0")}:${String(next.alarm.m).padStart(2, "0")}` : "";
    if (key === calKey) return;
    calKey = key;
    const day = picked ?? now;
    const isToday = sameDay(day, now);
    bigDay.textContent = String(day.getDate());
    bigWeekday.textContent = day.toLocaleDateString(lang, { weekday: "long" });
    bigWeekday.classList.toggle("other", !isToday);
    bigMonth.textContent = day.toLocaleDateString(lang, { month: "long", year: "numeric" });
    const diff = Math.round((new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / DAY_MS);
    relative.textContent = diff === 0 ? "" : diff === 1 ? t("Tomorrow") : diff === -1 ? t("Yesterday")
      : diff > 0 ? t("In {0} days", { 0: diff }) : t("{0} days ago", { 0: -diff });
    const onThisMonth = shown.getFullYear() === now.getFullYear() && shown.getMonth() === now.getMonth();
    todayBtn.hidden = onThisMonth && !picked;
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
      const date = new Date(shown.getFullYear(), shown.getMonth(), d);
      const cls = ["cal-d"];
      if (sameDay(date, now)) cls.push("today");
      if (picked && sameDay(date, picked)) cls.push("picked");
      if ((first + d - 1) % 7 >= 5) cls.push("weekend");
      const cell = h("span", { class: cls.join(" "), text: String(d) });
      cell.dataset.day = String(d);
      grid.append(cell);
    }
  }

  function syncWorld(now: Date) {
    const key = `${Math.floor(now.getTime() / 60_000)}~${Tools.cities.map((c) => c.name).join()}~${picking}`;
    if (key !== mapKey) {
      mapKey = key;
      drawMap(now);
    }
    if (picking != null) hint.hidden = false;
    const ck = `${now.getHours()}:${now.getMinutes()}~${Tools.cities.map((c) => c.name).join()}~${picking}`;
    if (ck === cityKey) return;
    cityKey = ck;
    clear(cities);
    const here = hereCity(now);
    const sun = subsolarPoint(now);
    Tools.cities.forEach((c, i) => {
      const ct = cityTime(c.zone, now);
      const day = isDay(c.lat, c.lon, sun);
      const chip = h("button", {
        class: `wm-city${c === here ? " here" : ""}${picking === i ? " picking" : ""}`,
        title: t("Click, then click the map to change it. Scroll to cycle."),
        onclick: (e: Event) => {
          e.stopPropagation();
          picking = picking === i ? null : i;
          if (picking == null) hint.hidden = true;
          State.notify();
        },
      },
      h("span", { class: "wm-name" }, svg(day ? ICONS.sun : ICONS.moon, 8, { stroke: 2 }), h("b", { text: c.name })),
      h("span", { class: "wm-time", text: ct.time }),
      h("span", { class: "wm-off", text: c === here ? t("Here") : ct.offset }));
      chip.addEventListener("wheel", (e) => {
        e.preventDefault();
        Tools.cycleCity(i, e.deltaY > 0 ? 1 : -1);
      }, { passive: false });
      cities.append(chip);
    });
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
    geo = { ox, oy, pitch };
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
    const here = hereCity(now);
    const xy = (lat: number, lon: number) => ({
      x: ox + ((lon + 180) / MAP_STEP) * pitch,
      y: oy + ((MAP_TOP_LAT - lat) / MAP_STEP) * pitch,
    });
    Tools.cities.forEach((c, i) => {
      const p = xy(c.lat, c.lon);
      const mine = c === here;
      const pick = picking === i;
      g.fillStyle = pick ? "rgba(255,255,255,0.3)" : mine ? "rgba(52,211,153,0.25)" : "rgba(255,180,84,0.22)";
      g.beginPath();
      g.arc(p.x, p.y, pick ? 7 : mine ? 6 : 5, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = pick ? "#fff" : mine ? "#34D399" : "#FFB454";
      g.beginPath();
      g.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
      g.fill();
    });
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

  // Leaving the page drops a half-done pick.
  State.subscribe(() => {
    if (picking != null && (State.view !== "time" || State.mode !== "expanded")) picking = null;
  });

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

// CLOVE fork: the StandBy page — cards you swipe through, like an iPhone on its side.
//
//   [ Streaks: All · GitHub · Gitea · LeetCode ]  →  [ GitHub ]  →  [ Gitea ]  →  [ LeetCode ]  →  [ Calendar | World ]
//
// The streaks card comes first every time the page opens. A two-finger swipe on the touchpad, a drag with the
// mouse (a quick flick is enough), the ← → keys or the dots move between cards. The cards slide on the iOS sheet
// curve, rubber-band at the ends, and only the cards for connected services are there.

import { State } from "../core/state";
import {
  SOURCES, SOURCE_NAMES, Streaks, stats, type DayCounts, type StreakSource, type StreakStats,
} from "../core/streaks";
import { N_, t, tl } from "../i18n/i18n";
import { clear, h, svg } from "./dom";
import { ICONS } from "./icons";
import { PILL_LOGOS } from "./logos";
import type { ViewActions, ViewHost } from "./views";

type CardSource = StreakSource | "all";

/** Each source's hue; the heatmap steps it from faint to full (one hue, dark to bright on the dark card). */
const HUE: Record<CardSource, string> = { all: "52,211,153", github: "57,211,83", gitea: "132,196,72", leetcode: "255,161,22" };
const LOGO: Record<StreakSource, string | undefined> = {
  github: PILL_LOGOS.integration_github, gitea: PILL_LOGOS.integration_gitea, leetcode: undefined,
};
const LEETCODE_LOGO = "M13.483 0a1.374 1.374 0 0 0-.961.438L7.116 6.226l-3.854 4.126a5.266 5.266 0 0 0-1.209 2.104 5.35 5.35 0 0 0-.125.513 5.527 5.527 0 0 0 .062 2.362 5.83 5.83 0 0 0 .349 1.017 5.938 5.938 0 0 0 1.271 1.818l4.277 4.193.039.038c2.248 2.165 5.852 2.133 8.063-.074l2.396-2.392c.54-.54.54-1.414.003-1.955a1.378 1.378 0 0 0-1.951-.003l-2.396 2.392a3.021 3.021 0 0 1-4.205.038l-.02-.019-4.276-4.193c-.652-.64-.972-1.469-.948-2.263a2.68 2.68 0 0 1 .066-.523 2.545 2.545 0 0 1 .619-1.164L9.13 8.114c1.058-1.134 3.204-1.27 4.43-.278l3.501 2.831c.593.48 1.461.387 1.94-.207a1.384 1.384 0 0 0-.207-1.943l-3.5-2.831c-.8-.647-1.766-1.045-2.774-1.202l2.015-2.158A1.384 1.384 0 0 0 13.483 0zm-2.866 12.815a1.38 1.38 0 0 0-1.38 1.382 1.38 1.38 0 0 0 1.38 1.382H20.79a1.38 1.38 0 0 0 1.38-1.382 1.38 1.38 0 0 0-1.38-1.382z";

function logoFor(src: CardSource): string | undefined {
  if (src === "leetcode") return LEETCODE_LOGO;
  if (src === "all") return undefined;
  return LOGO[src];
}

function fmtDate(key: string | null, lang?: string): string {
  if (!key) return "—";
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(lang, { day: "numeric", month: "short" });
}

// ── One streak card ─────────────────────────────────────────────────────────────

interface CardHost {
  el: HTMLElement;
  sync(): void;
}

function buildStreakCard(fixed: StreakSource | null, actions: ViewActions): CardHost {
  let source: CardSource = fixed ?? "all";
  const title = h("div", { class: "sk-title" });
  const pills = h("div", { class: "sk-pills" });
  const grid = h("div", { class: "sk-grid" });
  const months = h("div", { class: "sk-months" });
  const hover = h("div", { class: "sk-hover" });
  const legend = h("div", { class: "sk-legend" });
  const current = h("div", { class: "sk-current" });
  const stat = h("div", { class: "sk-stats" });
  const body = h("div", { class: "sk-body" },
    h("div", { class: "sk-main" }, h("div", { class: "sk-head" }, title, pills), months, grid,
      h("div", { class: "sk-foot" }, hover, legend)),
    h("div", { class: "sk-side" }, current, stat));
  const connect = h("div", { class: "sk-connect" });
  const el = h("div", { class: "card sk-card" }, body, connect);
  let key = "";

  // Hover a day: its count and date under the grid.
  grid.addEventListener("mousemove", (e) => {
    const cell = (e.target as HTMLElement).closest<HTMLElement>("i[data-date]");
    if (!cell) return;
    const n = Number(cell.dataset.count);
    const lang = document.documentElement.lang || undefined;
    hover.textContent = n === 1
      ? t("1 contribution on {0}", { 0: fmtDate(cell.dataset.date ?? null, lang) })
      : t("{0} contributions on {1}", { 0: n, 1: fmtDate(cell.dataset.date ?? null, lang) });
  });
  grid.addEventListener("mouseleave", () => { hover.textContent = ""; });

  function connectedSources(): StreakSource[] {
    return SOURCES.filter((s) => Streaks.connected(s));
  }

  function data(): DayCounts | null {
    return source === "all" ? Streaks.combined() : Streaks.days(source);
  }

  function renderConnect() {
    clear(connect);
    const lcField = h("input", { class: "sk-input", type: "text", placeholder: tl("LeetCode user name"), spellcheck: false }) as HTMLInputElement;
    lcField.value = Streaks.leetcodeUser;
    lcField.addEventListener("pointerdown", () => {
      actions.keyboard(true);
      window.setTimeout(() => lcField.focus(), 120);
    });
    lcField.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && lcField.value.trim()) {
        void Streaks.setLeetcode(lcField.value);
        lcField.blur();
      } else if (e.key === "Escape") lcField.blur();
    });
    lcField.addEventListener("blur", () => actions.keyboard(false));
    const wants = fixed ?? null;
    const showGit = !wants || wants === "github" || wants === "gitea";
    const showLc = !wants || wants === "leetcode";
    connect.append(
      h("div", { class: "sk-connect-title", text: t("Connect to see your streaks") }),
      h("div", { class: "sk-connect-sub", text: t("GitHub and Gitea come from their connections; LeetCode needs only your user name.") }),
      h("div", { class: "sk-connect-row" },
        ...(showGit ? [h("button", {
          class: "sk-connect-btn", onclick: (e: Event) => { e.stopPropagation(); actions.openSettingsWindow(); },
        }, svg(ICONS.gear, 11), h("span", { text: t("Connect GitHub or Gitea") }))] : []),
        ...(showLc ? [lcField] : [])),
      ...(Streaks.leetcodeError && showLc ? [h("div", { class: "sk-error", text: t("LeetCode: {0}", { 0: Streaks.leetcodeError }) })] : []),
    );
  }

  function renderStats(s: StreakStats, src: CardSource) {
    const lang = document.documentElement.lang || undefined;
    clear(current);
    current.append(
      h("div", { class: "sk-label", text: t("Current streak") }),
      h("div", { class: "sk-hero" }, h("b", { text: String(s.current) }), h("span", { text: s.current === 1 ? t("day") : t("days") })),
      h("div", { class: "sk-range", text: s.current ? `${fmtDate(s.currentFrom, lang)} → ${fmtDate(s.to, lang)}` : t("Start one today") }),
    );
    current.style.setProperty("--hue", HUE[src]);
    clear(stat);
    // The dates behind each number show on hover; the card keeps to the numbers.
    const row = (label: string, value: string, sub: string) =>
      h("div", { class: "sk-stat", title: sub }, h("span", { class: "sk-label", text: label }), h("b", { text: value }));
    stat.append(
      row(t("Longest"), `${s.longest} ${s.longest === 1 ? t("day") : t("days")}`, s.longest ? `${fmtDate(s.longestFrom, lang)} → ${fmtDate(s.longestTo, lang)}` : ""),
      row(t("Total"), s.total.toLocaleString(lang), t("last year")),
      row(t("Best day"), String(s.best), fmtDate(s.bestDate, lang)),
      row(t("Average"), s.average.toFixed(1), t("per day")),
    );
  }

  function renderGrid(s: StreakStats, src: CardSource) {
    clear(grid);
    clear(months);
    grid.style.setProperty("--hue", HUE[src]);
    const lang = document.documentElement.lang || undefined;
    let lastMonth = -1;
    s.weeks.forEach((week, w) => {
      const col = h("div", { class: "sk-col" });
      for (const c of week) {
        const cell = h("i", { class: `l${c ? c.level : "x"}` });
        if (c) {
          cell.dataset.date = c.date;
          cell.dataset.count = String(c.count);
        }
        col.append(cell);
      }
      grid.append(col);
      const first = week.find(Boolean);
      const m = first ? Number(first.date.slice(5, 7)) : lastMonth;
      if (first && m !== lastMonth && Number(first.date.slice(8)) <= 7) {
        const label = h("span", { text: new Date(2026, m - 1, 1).toLocaleDateString(lang, { month: "short" }) });
        label.style.left = `calc(${w} * var(--pitch))`;
        months.append(label);
        lastMonth = m;
      }
    });
    clear(legend);
    legend.append(h("span", { text: t("Less") }));
    for (let l = 0; l <= 4; l++) legend.append(h("i", { class: `l${l}` }));
    legend.append(h("span", { text: t("More") }));
    legend.style.setProperty("--hue", HUE[src]);
  }

  function renderHead() {
    clear(title);
    const logo = logoFor(source);
    if (logo) title.append(svg(logo, 12));
    title.append(h("b", { text: source === "all" ? t("Streaks") : SOURCE_NAMES[source] }));
    clear(pills);
    if (fixed) return;
    const avail = connectedSources();
    if (avail.length < 2) return;
    for (const s of ["all", ...avail] as CardSource[]) {
      pills.append(h("button", {
        class: `sk-pill${s === source ? " on" : ""}`,
        onclick: (e: Event) => {
          e.stopPropagation();
          source = s;
          key = "";
          State.notify();
        },
      }, s === "all" ? t("All") : SOURCE_NAMES[s]));
    }
  }

  return {
    el,
    sync() {
      // A source he switched to that has since gone: back to all.
      if (!fixed && source !== "all" && !Streaks.connected(source)) source = "all";
      const days = data();
      const today = new Date().toDateString();
      const k = [source, today, days ? days.size : -1, days ? [...days.values()].reduce((a, b) => a + b, 0) : 0,
        Streaks.leetcodeUser, Streaks.leetcodeError, connectedSources().join(), document.documentElement.lang].join("~");
      if (k === key) return;
      key = k;
      const has = !!days && (fixed ? Streaks.connected(fixed) : connectedSources().length > 0);
      el.classList.toggle("empty", !has);
      renderHead();
      if (!has || !days) {
        renderConnect();
        return;
      }
      clear(connect);
      const s = stats(days);
      renderGrid(s, source);
      renderStats(s, source);
    },
  };
}

// ── The deck ────────────────────────────────────────────────────────────────────

export function buildStandby(time: ViewHost, actions: ViewActions): ViewHost {
  const main = buildStreakCard(null, actions);
  const per: Record<StreakSource, CardHost> = {
    github: buildStreakCard("github", actions),
    gitea: buildStreakCard("gitea", actions),
    leetcode: buildStreakCard("leetcode", actions),
  };
  // The calendar and world clocks keep their own two-card layout as the last page.
  time.el.classList.remove("view", "on");
  time.el.classList.add("sb-page-two");

  const track = h("div", { class: "sb-track" });
  const dots = h("div", { class: "sb-dots" });
  const el = h("div", { class: "view sb" }, h("div", { class: "sb-viewport" }, track), dots);

  let pages: HTMLElement[] = [];
  let index = 0;
  let pagesKey = "";
  let wasOpen = false;

  function wrap(card: HTMLElement): HTMLElement {
    return h("div", { class: "sb-page" }, card);
  }

  function rebuild() {
    const want: { id: string; el: HTMLElement }[] = [{ id: "all", el: main.el }];
    for (const s of SOURCES) if (Streaks.connected(s)) want.push({ id: s, el: per[s].el });
    want.push({ id: "time", el: time.el });
    const k = want.map((p) => p.id).join("|");
    if (k === pagesKey) return;
    pagesKey = k;
    clear(track);
    pages = want.map((p) => {
      const page = p.id === "time" ? h("div", { class: "sb-page" }, p.el) : wrap(p.el);
      page.dataset.id = p.id;
      track.append(page);
      return page;
    });
    clear(dots);
    pages.forEach((p, i) => dots.append(h("button", {
      class: "sb-dot", title: p.dataset.id === "time" ? t("Calendar and world clocks") : t("Streaks"),
      onclick: (e: Event) => { e.stopPropagation(); go(i); },
    })));
    index = Math.min(index, pages.length - 1);
    place(0, false);
  }

  function place(dragPx: number, animate: boolean) {
    track.style.transition = animate ? "transform 520ms cubic-bezier(0.32, 0.72, 0, 1)" : "none";
    track.style.transform = `translate3d(calc(${-index * 100}% + ${dragPx}px), 0, 0)`;
    [...dots.children].forEach((d, i) => d.classList.toggle("on", i === index));
    pages.forEach((p, i) => p.classList.toggle("current", i === index));
  }

  function go(i: number) {
    const next = Math.max(0, Math.min(pages.length - 1, i));
    if (next === index) {
      // At an end: a small rubber-band nudge says there's nothing more that way.
      const dir = i > index ? -1 : 1;
      place(dir * 18, true);
      window.setTimeout(() => place(0, true), 140);
      return;
    }
    index = next;
    place(0, true);
    State.notify();
  }

  // Two-finger swipe on the touchpad (horizontal wheel): one card per gesture.
  let wheelAcc = 0;
  let wheelLock = 0;
  el.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;     // vertical: the calendar's months, the city clocks
    e.preventDefault();
    const now = performance.now();
    if (now < wheelLock) return;
    wheelAcc += e.deltaX;
    if (Math.abs(wheelAcc) > 40) {
      go(index + (wheelAcc > 0 ? 1 : -1));
      wheelAcc = 0;
      wheelLock = now + 420;
    }
  }, { passive: false });

  // Drag with the mouse: follows the pointer, rubber-bands at the ends, a quick flick is enough.
  let drag: { x: number; y: number; t: number; id: number; moving: boolean } | null = null;
  let suppressClick = false;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("input,button")) return;
    drag = { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId, moving: false };
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    let dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moving) {
      if (Math.abs(dx) < 8 || Math.abs(dx) < Math.abs(dy)) return;
      drag.moving = true;
      el.setPointerCapture(e.pointerId);
    }
    const atEnd = (dx > 0 && index === 0) || (dx < 0 && index === pages.length - 1);
    if (atEnd) dx = Math.sign(dx) * Math.pow(Math.abs(dx), 0.75);    // friction past the ends
    place(dx, false);
  });
  const end = (e: PointerEvent) => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    drag = null;
    if (!d.moving) return;
    suppressClick = true;
    window.setTimeout(() => { suppressClick = false; }, 0);
    const dx = e.clientX - d.x;
    const v = Math.abs(dx) / Math.max(1, performance.now() - d.t);
    const width = el.clientWidth || 600;
    if (Math.abs(dx) > width * 0.22 || v > 0.11) {
      const before = index;
      index = Math.max(0, Math.min(pages.length - 1, index + (dx < 0 ? 1 : -1)));
      if (index !== before) State.notify();
    }
    place(0, true);
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("click", (e) => {
    if (suppressClick) {
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);

  window.addEventListener("keydown", (e) => {
    if (State.view !== "time" || State.mode !== "expanded") return;
    if ((e.target as HTMLElement)?.closest?.("input")) return;
    if (e.key === "ArrowRight") go(index + 1);
    else if (e.key === "ArrowLeft") go(index - 1);
  });

  return {
    el,
    sync() {
      const open = State.view === "time" && State.mode === "expanded";
      if (open && !wasOpen) {
        // The streaks card first, every time the page opens.
        index = 0;
        void Streaks.refreshLeetcode();
        rebuild();
        place(0, false);
      }
      wasOpen = open;
      if (!open) return;
      rebuild();
      main.sync();
      for (const s of SOURCES) if (Streaks.connected(s)) per[s].sync();
      time.sync();
    },
  };
}

// Strings the cards show (the i18n checker reads these).
void [N_("Streaks"), N_("All")];

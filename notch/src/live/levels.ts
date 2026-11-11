// (English only for now: these strings are not in the translation tables yet.)
// The Controls page's two sliders, as on the Control Center: the speakers' volume and the screen's brightness
// (src-tauri/src/live/mod.rs: wpctl and brightnessctl). Read again every two seconds while the page is open, so
// the volume keys and the brightness keys show up here.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "../core/bridge";
import { State } from "../core/state";
import { h, svg, clear } from "../views/dom";
import { ICONS } from "../views/icons";
import { icon } from "./icons";

interface Levels {
  volume: number | null;
  muted: boolean;
  brightness: number | null;
}

type Kind = "volume" | "brightness";

let levels: Levels = { volume: null, muted: false, brightness: null };
let askedAt = 0;
/** Values being dragged to, sent at most every 70 ms. */
const pending: Partial<Record<Kind, number>> = {};
let flushTimer: number | null = null;

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!IS_TAURI) return null;
  try {
    return await invoke<T>(cmd, args);
  } catch {
    return null;
  }
}

function apply(next: Levels | null) {
  if (!next) return;
  levels = next;
  State.notify();
}

function flush() {
  flushTimer = null;
  for (const kind of Object.keys(pending) as Kind[]) {
    const value = pending[kind];
    delete pending[kind];
    void call<Levels>("live_set_level", { kind, value }).then(apply);
  }
}

export const LevelsCtl = {
  get now(): Levels {
    return levels;
  },
  /** Reads the levels again, at most every two seconds (or now). */
  refresh(now = false) {
    if (!now && Date.now() - askedAt < 2000) return;
    askedAt = Date.now();
    void call<Levels>("live_levels").then(apply);
  },
  set(kind: Kind, value: number) {
    levels = { ...levels, [kind]: value, ...(kind === "volume" ? { muted: false } : {}) };
    pending[kind] = value;
    flushTimer ??= window.setTimeout(flush, 70);
  },
  toggleMute() {
    levels = { ...levels, muted: !levels.muted };
    State.notify();
    void call<Levels>("live_set_level", { kind: "mute", value: null }).then(apply);
  },
};

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

function volumeIcon(v: number, muted: boolean): SVGSVGElement {
  return svg(muted || v <= 0 ? ICONS.speakerOff : ICONS.speakerOn, 14);
}

/** One slider: a glass track, its white fill, the icon inside (inverted over the fill), the percent on hover. */
function slider(kind: Kind): { el: HTMLElement; sync(): void } {
  const fill = h("div", { class: "lvl-fill" });
  const pct = h("span", { class: "lvl-pct" });
  const glyph = h("button", {
    class: "lvl-icon", title: kind === "volume" ? "Mute" : "Brightness",
    onclick: (e: Event) => {
      e.stopPropagation();
      if (kind === "volume") LevelsCtl.toggleMute();
    },
  });
  const track = h("div", { class: "lvl-track", title: kind === "volume" ? "Sound" : "Display" }, fill, glyph, pct);
  const el = h("div", { class: `lvl lvl-${kind}` }, track);
  let dragging = false;
  let shownKey = "";

  const draw = (v: number, muted: boolean) => {
    fill.style.width = `${(muted ? 0 : clamp01(v)) * 100}%`;
    pct.textContent = `${Math.round(clamp01(v) * 100)}%`;
    const key = kind === "volume" ? `${muted || v <= 0}` : "sun";
    if (key !== shownKey) {
      shownKey = key;
      clear(glyph);
      glyph.append(kind === "volume" ? volumeIcon(v, muted) : icon("sun", 14, 2));
    }
  };
  const at = (x: number) => {
    const r = track.getBoundingClientRect();
    return clamp01((x - r.left) / Math.max(1, r.width));
  };
  const move = (x: number) => {
    const v = at(x);
    draw(v, false);
    LevelsCtl.set(kind, v);
  };

  track.addEventListener("pointerdown", (e) => {
    if ((e.target as HTMLElement).closest(".lvl-icon")) return;
    e.stopPropagation();
    dragging = true;
    track.classList.add("dragging");
    track.setPointerCapture(e.pointerId);
    move(e.clientX);
  });
  track.addEventListener("pointermove", (e) => {
    if (dragging) move(e.clientX);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    track.classList.remove("dragging");
  };
  track.addEventListener("pointerup", end);
  track.addEventListener("pointercancel", end);
  // The wheel moves it five percent a notch.
  track.addEventListener("wheel", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const now = LevelsCtl.now[kind] ?? 0;
    const v = clamp01(now + (e.deltaY < 0 ? 0.05 : -0.05));
    draw(v, false);
    LevelsCtl.set(kind, v);
  }, { passive: false });

  return {
    el,
    sync() {
      const value = LevelsCtl.now[kind];
      el.style.display = value == null ? "none" : "";
      if (value == null || dragging) return;
      draw(value, kind === "volume" && LevelsCtl.now.muted);
    },
  };
}

/** Sound and Display, one under the other. */
export function buildLevels(): { el: HTMLElement; sync(): void } {
  const sound = slider("volume");
  const display = slider("brightness");
  return {
    el: h("div", { class: "lvls" }, sound.el, display.el),
    sync() {
      LevelsCtl.refresh();
      sound.sync();
      display.sync();
    },
  };
}

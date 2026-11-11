// Glyphs of the live activities: one 24×24 path each, drawn as 2 px round
// strokes (views/dom.ts svg(…, { stroke })) unless listed in FILLED.

import { svg } from "../views/dom";

export const LI = {
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  phoneDown: "M3.5 14.5c5-5 12-5 17 0l-1.8 2.6-3.7-1.4v-2.5a9 9 0 0 0-6 0v2.5l-3.7 1.4z",
  video: "M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5zM15 10.5l6-3.5v10l-6-3.5",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3",
  timer: "M12 8v5l3 2M12 4a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9.5 1.5h5",
  stopwatch: "M12 6a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 10v4M10 2h4M18.5 6.5l1.5-1.5",
  play: "M7 4.5v15l12.5-7.5z",
  pause: "M7 4.5h3.5v15H7zM13.5 4.5H17v15h-3.5z",
  next: "M4 5v14l10-7zM15 5v14l6-7zM21 5v14",
  prev: "M20 5v14l-10-7zM9 5v14l-6-7zM3 5v14",
  stop: "M7 7h10v10H7z",
  x: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  plus: "M12 5v14M5 12h14",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  arrowUp: "M12 20V5M5.5 11.5L12 5l6.5 6.5",
  turnLeft: "M9 20v-7a4 4 0 0 1 4-4h0M4 9l5-5 5 5M9 4v9",
  turnRight: "M15 20v-7a4 4 0 0 0-4-4h0M20 9l-5-5-5 5M15 4v9",
  bearLeft: "M14 20v-6L7 7M7 13V7h6",
  bearRight: "M10 20v-6l7-7M17 13V7h-6",
  uturn: "M7 20V10a5 5 0 0 1 10 0v4M13.5 11.5L17 15l3.5-3.5",
  roundabout: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 22v-6M12 8V2M9 5l3-3 3 3",
  pin: "M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11zM12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  car: "M5 11l1.6-4.2A2 2 0 0 1 8.5 5.5h7a2 2 0 0 1 1.9 1.3L19 11M4 11h16a1 1 0 0 1 1 1v4.5H3V12a1 1 0 0 1 1-1zM6 16.5V19M18 16.5V19M7 13.8h.01M17 13.8h.01",
  bike: "M5.5 13a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM18.5 13a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM5.5 16.5L9 9h5l4.5 7.5M9 9L8 6.5H6M14 9l1-3h2.5",
  box: "M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5zM3.5 7.5L12 12l8.5-4.5M12 12v9",
  truck: "M2 6h11v10H2zM13 9.5h4.5L21 13v3h-8zM6.5 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM17 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  store: "M4 10v10h16V10M3 10l1.5-6h15L21 10a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0zM9.5 20v-5h5v5",
  home: "M4 11l8-7 8 7v9h-5.5v-5.5h-5V20H4z",
  chart: "M3 17l5-5 4 3 8-9M15 6h5v5",
  trophy: "M7.5 4h9v5a4.5 4.5 0 0 1-9 0zM7.5 6H4a3.5 3.5 0 0 0 3.8 4M16.5 6H20a3.5 3.5 0 0 1-3.8 4M12 13.5V17M8.5 20h7M10 17h4",
  battery: "M3.5 8h14a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 2 14.5v-5A1.5 1.5 0 0 1 3.5 8zM22 10.5v3",
  bolt: "M13 2L4.5 13.5H11L10 22l8.5-11.5H12z",
  headphones: "M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v6H6a2 2 0 0 1-2-2zM20 14h-3v6h1a2 2 0 0 0 2-2z",
  earbuds: "M8 3a4 4 0 0 0-4 4v3a3 3 0 0 0 3 3v6.5a1.5 1.5 0 0 0 3 0V7a4 4 0 0 0-2-4zM16 3a4 4 0 0 1 4 4v3a3 3 0 0 1-3 3v6.5a1.5 1.5 0 0 1-3 0V7a4 4 0 0 1 2-4z",
  handset: "M8 2.5h8a2 2 0 0 1 2 2v15a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2zM10.5 18.5h3",
  mouse: "M12 3a5.5 5.5 0 0 1 5.5 5.5v7a5.5 5.5 0 0 1-11 0v-7A5.5 5.5 0 0 1 12 3zM12 7v3.5",
  keyboard: "M3.5 6.5h17A1.5 1.5 0 0 1 22 8v8a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 16V8a1.5 1.5 0 0 1 1.5-1.5zM6 10.5h.01M10 10.5h.01M14 10.5h.01M18 10.5h.01M7 14h10",
  link: "M9.5 14.5l5-5M10.5 6.5l1.2-1.2a4.2 4.2 0 0 1 6 6l-1.2 1.2M13.5 17.5l-1.2 1.2a4.2 4.2 0 0 1-6-6l1.2-1.2",
  camera: "M4 8h3l1.5-2.5h7L17 8h3a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 20 19H4a1.5 1.5 0 0 1-1.5-1.5v-8A1.5 1.5 0 0 1 4 8zM12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z",
  lock: "M6.5 11h11A1.5 1.5 0 0 1 19 12.5v6a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18.5v-6A1.5 1.5 0 0 1 6.5 11zM8 11V8a4 4 0 0 1 8 0v3",
  unlock: "M6.5 11h11A1.5 1.5 0 0 1 19 12.5v6a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18.5v-6A1.5 1.5 0 0 1 6.5 11zM8 11V7.5a4 4 0 0 1 7.6-1.7",
  faceId: "M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M9 9v1.5M15 9v1.5M12 9v4h-1M9 15.5a4.5 4.5 0 0 0 6 0",
  fingerprint: "M12 10v4a8 8 0 0 1-1 4M8 19c.7-1.5 1-3.2 1-5v-4a3 3 0 0 1 6 0v3M15 16.5c-.2 1.5-.6 2.9-1.2 4M5.5 16c.3-1 .5-2 .5-3v-3a6 6 0 0 1 10-4.5M18 10.500v3c0 .8-.1 1.700-.2 2.500",
  key: "M15.500 3a5.500 5.500 0 1 0 0 11 5.500 5.500 0 0 0 0-11zM11.500 12.500L3 21M6 18l2.500 2.500M17 7.500h.01",
  wallet: "M4 6.500h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-12A1.500 1.500 0 0 1 4.500 4H16M16.500 13h.01",
  folder: "M3 6.500A1.500 1.500 0 0 1 4.500 5H9l2 2.500h8.500A1.500 1.500 0 0 1 21 9v8.500a1.500 1.500 0 0 1-1.500 1.500h-15A1.500 1.500 0 0 1 3 17.500z",
  record: "M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14z",
  external: "M10 5H5v14h14v-5M14 4h6v6M20 4l-9 9",
  music: "M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  chevLeft: "M14.500 5.500L8 12l6.500 6.500",
  chevRight: "M9.500 5.500L16 12l-6.500 6.500",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  message: "M4 5h16v11H9l-5 4z",
  wave: "M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4",
  user: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4.500 20a7.500 7.500 0 0 1 15 0",
  activity: "M3 12h4l2.500-7 5 14 2.500-7h4",
} as const;

export type LiveIcon = keyof typeof LI;

/** Solid shapes: a stroke would hollow them out. */
const FILLED: ReadonlySet<LiveIcon> = new Set(["play", "pause", "next", "prev", "stop", "bolt", "record", "phone", "phoneDown"]);

export function icon(name: LiveIcon, size = 16, stroke = 2): SVGSVGElement {
  return FILLED.has(name) ? svg(LI[name], size) : svg(LI[name], size, { stroke });
}

/** The arrow for a turn, from OSRM's modifier. */
export function turnIcon(modifier: string): LiveIcon {
  switch (modifier) {
    case "left":
    case "sharp left": return "turnLeft";
    case "right":
    case "sharp right": return "turnRight";
    case "slight left": return "bearLeft";
    case "slight right": return "bearRight";
    case "uturn": return "uturn";
    case "roundabout": return "roundabout";
    case "arrive": return "pin";
    default: return "arrowUp";
  }
}

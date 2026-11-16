// Live activities with made-up data, for `npm run dev` in a browser (nothing
// here ships: main.ts only loads it in dev). In the console:
//   demo("ride")          the card, opened
//   demo("ride", true)    the compact pill
//   demo.all              every scenario's name

import { Live } from "../src/core/live";
import { State } from "../src/core/state";
import { LiveCtl, type SystemSnapshot } from "../src/live/control";
import { LevelsCtl } from "../src/live/levels";
import type { Island } from "../src/island/island";

const now = () => Date.now();

function sys(over: Partial<SystemSnapshot> = {}) {
  LiveCtl.system_({
    mic: [], camera: [], screen: [], devices: [], hotspot: null, locked: false,
    battery: { present: true, percent: 64, charging: false, plugged: false },
    ...over,
  });
}

const player = (over: Record<string, unknown>) => ({
  bus: "org.mpris.MediaPlayer2.demo", app: "Spotify", source: "spotify", title: "Blinding Lights", artist: "The Weeknd",
  album: "After Hours", artUrl: null, url: "", duration: 200, position: 42, positionAt: now(), playing: true,
  canNext: true, canPrev: true, canSeek: true, ...over,
});

const scenarios: Record<string, () => void> = {
  media: () => LiveCtl.players_([player({}) as never]),
  youtube: () => LiveCtl.players_([player({ app: "Chrome", source: "youtube", title: "lofi hip hop radio – beats to relax/study to", artist: "Lofi Girl", duration: 0, canPrev: false, canSeek: false }) as never]),
  applemusic: () => LiveCtl.players_([player({ app: "Chrome", source: "applemusic", title: "Espresso", artist: "Sabrina Carpenter" }) as never]),
  call: () => LiveCtl.push({ op: "call", name: "Priya Sharma", app: "WhatsApp", video: true }),
  phonecall: () => LiveCtl.push({ op: "call", name: "Mom", app: "Phone" }),
  timer: () => void LiveCtl.startTimer(754, "Pasta"),
  timerdone: () => void LiveCtl.startTimer(1, "Tea"),
  stopwatch: () => LiveCtl.stopwatch("start"),
  memo: () => void Live.upsert("memo", "memo", { path: "/home/me/Music/Voice Memos/Memo.wav", state: "recording", since: now() - 24_000, seconds: 0, levels: Array.from({ length: 40 }, (_, i) => Math.abs(Math.sin(i * 0.7)) * 0.9) }, now()),
  recording: () => sys({ screen: [{ app: "Screen recording", pid: 1, since: now() - 24_000 }] }),
  nav: () => void Live.upsert("nav", "nav", {
    destination: "India Gate", origin: "Home", stepIndex: 0, distance: 4200, duration: 780, etaAt: now() + 780_000, source: "route",
    steps: [{ text: "Turn left onto Kartavya Path", distance: 300, modifier: "left" }, { text: "Continue on C-Hexagon", distance: 3900, modifier: "straight" }, { text: "You have arrived", distance: 0, modifier: "arrive" }],
    line: [[77.2, 28.6], [77.205, 28.604], [77.21, 28.603], [77.215, 28.608], [77.222, 28.61], [77.229, 28.6129]],
  }, now()),
  ride: () => LiveCtl.notification({ id: 1, app: "Uber", summary: "Uber", body: "Ramesh Kumar is arriving in 3 mins in a white Swift DL 01 AB 1234. Your PIN is 4821" }),
  rapido: () => LiveCtl.notification({ id: 1, app: "Rapido", summary: "Captain assigned", body: "Captain Suresh is on the way. OTP 7731" }),
  delivery: () => LiveCtl.notification({ id: 2, app: "Blinkit", summary: "Order out for delivery", body: "Noman is on the way with your order and will arrive by 2:15 pm" }),
  zepto: () => LiveCtl.notification({ id: 2, app: "Zepto", summary: "Your order is packed", body: "Arriving in 8 minutes" }),
  amazon: () => LiveCtl.notification({ id: 2, app: "Amazon Shopping", summary: "Shipped", body: "Your package with boAt Airdopes has shipped and arrives tomorrow" }),
  flipkart: () => LiveCtl.notification({ id: 2, app: "Flipkart", summary: "Delivered", body: "Your order has been delivered. Enjoy!" }),
  sports: () => void Live.upsert("sports:1", "sports", {
    eventId: "1", sport: "cricket", league: "IPL 2026", state: "in", status: "18.2 ov", summary: "MI need 24 runs in 10 balls", startsAt: now(), link: "",
    home: { abbr: "MI", name: "Mumbai Indians", score: "182/4 (18.2 ov)", logo: "", winner: false },
    away: { abbr: "CSK", name: "Chennai Super Kings", score: "205/6", logo: "", winner: false },
  }, now()),
  football: () => void Live.upsert("sports:2", "sports", {
    eventId: "2", sport: "soccer", league: "Premier League", state: "in", status: "67'", summary: "", startsAt: now(), link: "",
    home: { abbr: "ARS", name: "Arsenal", score: "2", logo: "", winner: false },
    away: { abbr: "LIV", name: "Liverpool", score: "1", logo: "", winner: false },
  }, now()),
  stock: () => void Live.upsert("stock:TSLA", "stock", {
    symbol: "TSLA", code: "TSLA", name: "Tesla Inc", price: 378.05, change: 19.83, changePct: 5.54, currency: "USD", prevClose: 358.22, marketOpen: true,
    series: Array.from({ length: 60 }, (_, i) => 360 + Math.sin(i / 5) * 6 + i * 0.3 + Math.cos(i * 1.7) * 2),
  }, now()),
  stockdown: () => void Live.upsert("stock:RELIANCE", "stock", {
    symbol: "RELIANCE", code: "RELIANCE-IN", name: "Reliance Industries Ltd", price: 1324.4, change: -12.6, changePct: -0.94, currency: "INR", prevClose: 1337, marketOpen: false,
    series: Array.from({ length: 60 }, (_, i) => 1337 - i * 0.2 + Math.sin(i / 4) * 5),
  }, now()),
  faceid: () => LiveCtl.push({ op: "auth", method: "face", ok: true, detail: "Face recognised" }),
  fingerprint: () => LiveCtl.push({ op: "auth", method: "fingerprint", ok: null, detail: "Touch the sensor" }),
  authfail: () => LiveCtl.push({ op: "auth", method: "password", ok: false, detail: "Authentication failed" }),
  unlock: () => { sys({ locked: true }); sys({ locked: false }); },
  payment: () => LiveCtl.notification({ id: 3, app: "Google Pay", summary: "Payment successful", body: "You paid ₹450.00 to Zomato Ltd using UPI" }),
  device: () => { sys(); sys({ devices: [{ id: "a", name: "Aryan's AirPods Pro", kind: "headphones", percent: 82, charging: false }] }); },
  phone: () => { sys(); sys({ devices: [{ id: "p", name: "Pixel 9", kind: "phone", percent: 47, charging: true }] }); },
  battery: () => { sys({ battery: { present: true, percent: 21, charging: false, plugged: false } }); sys({ battery: { present: true, percent: 20, charging: false, plugged: false } }); },
  charging: () => { sys(); sys({ battery: { present: true, percent: 64, charging: true, plugged: true } }); },
  hotspot: () => { sys(); sys({ hotspot: { name: "Hotspot", ssid: "Aryan-Laptop", iface: "wlo1", clients: 2 } }); },
  camera: () => sys({ camera: ["Chrome"], mic: ["Chrome"] }),
  voice: () => LiveCtl.push({ op: "voice", phase: "speaking", heard: "open firefox and play some lofi", reply: "Opening Firefox and starting a lofi stream for you." }),
  listening: () => LiveCtl.push({ op: "voice", phase: "listening" }),
  many: () => { scenarios.media(); scenarios.timer(); scenarios.delivery(); scenarios.sports(); scenarios.stock(); sys({ mic: ["CLOVE"] }); },
};

export function installLiveDemo(island: Island) {
  const reset = () => {
    island.collapse();
    Live.clear();
    LiveCtl.players_([]);
    sys();
    localStorage.removeItem("clove.live.v1");
  };
  const demo = (name: string, compact = false) => {
    reset();
    scenarios[name]?.();
    window.setTimeout(() => (compact ? island.collapse() : island.openLive(null)), 200);
  };
  Object.assign(demo, { all: Object.keys(scenarios), reset, sys, hub: () => { reset(); island.openLive(null); } });
  Object.assign(window, { demo, __live: { LiveCtl, Live, State, island, LevelsCtl } });
}

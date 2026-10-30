// The Assistant pages of the CLOVE window: the CLOVE assistant's own window (clove/ui, served by the assistant on
// 127.0.0.1) shown inside this one, so there is one CLOVE app. This window's sidebar picks the page and the frame
// hides its own. The frame stays loaded while other pages are shown and is told when it is off screen, so it draws
// nothing then. If CLOVE isn't running the page says so, and can start its login service.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "../core/bridge";
import { h, clear } from "../views/dom";
import { hero } from "./hero";
import { card, row } from "./ui";

export type CloveView = "chat" | "activity" | "systems" | "prefs";
export const CLOVE_VIEWS: CloveView[] = ["chat", "activity", "systems", "prefs"];

/** How often the address is checked while the page is shown: CLOVE gets a new one each time it starts. */
const RECHECK_MS = 5000;
/** How long a start may take: the clove folder may be on a drive that mounts late. */
const START_WAIT_MS = 45_000;

async function windowUrl(): Promise<string | null> {
  if (!IS_TAURI) return null;
  try {
    return await invoke<string | null>("clove_window_url");
  } catch {
    return null;
  }
}

export class CloveFrame {
  readonly el = h("div", { class: "hub-clove" });
  private frame: HTMLIFrameElement | null = null;
  private url: string | null = null;
  private view: CloveView = "chat";
  private active = false;
  private windowShown = true;
  private timer: number | null = null;
  private starting = false;
  private checking = false;

  constructor(
    private readonly onView: (view: CloveView) => void,
    private readonly onAttention: (count: number) => void,
  ) {
    this.el.hidden = true;
    window.addEventListener("message", (e) => {
      if (!this.frame || !this.url || e.source !== this.frame.contentWindow) return;
      if (e.origin !== new URL(this.url).origin) return;
      const d = e.data as { type?: string; view?: string; count?: number } | null;
      if (!d || typeof d !== "object") return;
      if (d.type === "clove:view" && CLOVE_VIEWS.includes(d.view as CloveView)) {
        this.view = d.view as CloveView;
        this.onView(this.view);
      } else if (d.type === "clove:attention") {
        this.onAttention(Math.max(0, Number(d.count) || 0));
      }
    });
  }

  show(view: CloveView) {
    this.view = view;
    this.active = true;
    this.el.hidden = false;
    this.post({ type: "clove:view", view });
    this.postShown();
    void this.check();
    if (this.timer === null) this.timer = window.setInterval(() => void this.check(), RECHECK_MS);
  }

  hide() {
    this.active = false;
    this.el.hidden = true;
    this.postShown();
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
  }

  setWindowShown(shown: boolean) {
    this.windowShown = shown;
    this.postShown();
  }

  private post(msg: object) {
    if (!this.frame?.contentWindow || !this.url) return;
    this.frame.contentWindow.postMessage(msg, new URL(this.url).origin);
  }

  private postShown() {
    this.post({ type: "clove:shown", shown: this.active && this.windowShown });
  }

  /** Loads the frame when CLOVE appears or restarts (a new address), or says it isn't running. */
  private async check() {
    if (this.checking) return;
    this.checking = true;
    try {
      const url = await windowUrl();
      if (url && url === this.url && this.frame) return;
      if (url) this.load(url);
      else if (this.frame || !this.el.firstChild) this.offline();
    } finally {
      this.checking = false;
    }
  }

  private load(url: string) {
    this.url = url;
    this.starting = false;
    const frame = h("iframe", { title: "CLOVE", src: `${url}&embed=1&view=${this.view}` });
    frame.addEventListener("load", () => {
      this.post({ type: "clove:view", view: this.view });
      this.postShown();
    });
    clear(this.el);
    this.el.append(frame);
    this.frame = frame;
  }

  private offline(problem?: string) {
    this.frame = null;
    this.url = null;
    this.onAttention(0);
    const start = h("button", { class: "hub-btn primary", text: this.starting ? "Starting…" : "Start CLOVE" });
    start.disabled = this.starting;
    start.addEventListener("click", () => void this.start());
    const page = h(
      "div",
      { class: "hub-page" },
      hero("clove", "CLOVE isn't running", "The conversation, its tasks and their approvals show here once it is.", [start]),
      card(
        row("Starts with your session", "CLOVE runs as the systemd user service clove, so it is already on after you log in."),
        row("If it doesn't come up", "Its log is ~/.local/state/clove/clove.log; journalctl --user -u clove has the rest."),
      ),
    );
    if (problem) page.append(h("div", { class: "hub-warn", role: "alert", text: problem }));
    clear(this.el);
    this.el.append(h("div", { class: "hub-scroll" }, page));
  }

  private async start() {
    this.starting = true;
    this.offline();
    try {
      await invoke("clove_start");
    } catch (err) {
      this.starting = false;
      this.offline(String(err));
      return;
    }
    const until = Date.now() + START_WAIT_MS;
    while (Date.now() < until && !this.frame) {
      await new Promise((r) => setTimeout(r, 1000));
      const url = await windowUrl();
      if (url) {
        this.load(url);
        return;
      }
    }
    if (!this.frame) {
      this.starting = false;
      this.offline("CLOVE didn't come up within 45 seconds. See ~/.local/state/clove/clove.log.");
    }
  }
}

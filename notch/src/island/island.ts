// Clove Notch: DOM shell, sizing animation, CLOVE placement, mouse handling.
// Mirrors IslandRootView.swift + IslandWindowController.swift.

import { Tracked, Spring, clamp } from "../core/anim";
import { Bridge, IS_TAURI, onDragDrop } from "../core/bridge";
import {
  COMPACT_CLOCK_W, COMPACT_MAX_W, COMPACT_W, EXPANDED_CORNER, EXPANDED_W, NOTCH_W, PANEL_H, PANEL_W,
  ROUNDED_CORNER, TOP_GAP, VIEW_LAYOUTS, botPosition, chatPromptHeight,
  islandSize,
  QUESTION_PICKER_H,
  type BotEmoteName, type IslandMode, type IslandViewName, compactWidth, setCompactWidth } from "../core/layout";
import { FlowBridge } from "../core/flow";
import { Sound } from "../core/sound";
import { sanitizeDeclared, toggleDeclared } from "../core/pills";
import { State } from "../core/state";
import { LocalSend } from "../core/localsend";
import { t } from "../i18n/i18n";
import { APP_LOGOS } from "../views/logos";
import { ICONS } from "../views/icons";
import { SPOTIFY_ID, islandDances } from "../core/spotify";
import { BotEngine, hexToRGB } from "../mochi/engine";
import { Greeting } from "../mochi/greeting";
import { pruneMiniBots, syncMiniBotStates, tickMiniBots } from "../mochi/minibots";
import { SeasonCache, parseOutfit } from "../mochi/wardrobe";
import { UploadCanvas } from "../upload/canvas";
import { USC, UploadSeq } from "../upload/sequence";
import { closePlanCard, openPlanColor, planCardOpen } from "../views/usage";
import { buildHeader, buildViews, type ViewActions, type ViewHost } from "../views/views";
import { h, svg } from "../views/dom";
import { CompactLive, accentOf, buildLive, type LiveView } from "../live/view";
import { Live } from "../core/live";
import { IslandStateMachine } from "./fsm";
import { refreshHookPills } from "./integrations";
import { DesktopLink } from "./desktop";
import type { ViewCommand } from "./shortcuts";
import { DRAG_THRESHOLD } from "../mochi/desktop-logic";
import { Updates } from "./update";
import { UPDATE_BLUE, showsUpdateHint } from "../whats-new/whats-new";

const BOT_OVERHANG = 40;
const UPDATE_BLUE_RGB = hexToRGB(UPDATE_BLUE);
const CLAUDE_DESKTOP_ID = "agent_claude-desktop";
/** Extra canvas on each side of CLOVE, for the witch hat's brim and the Santa hat's tip. */
const BOT_SIDE = 24;
/** Same margin as the Rust hit test (src-tauri/src/island.rs). */
const HIT_MARGIN = 14;

/** The header's height with its margin (#header in live.css): added above a live card opened by hand. */
const HEADER_H = 34;

/** Pages narrower than the island's widest; the header can still make them wider (barWidth). */
const VIEW_WIDTH: Partial<Record<IslandViewName, number>> = {
  overview: 560, empty: 520, settings: 560,
};

/** The circle beside the pill: notifications, and the way into the launcher. */
const BUBBLE = 36;
const BUBBLE_GAP = 8;

/** The three views the drop sequence owns; leaving them stops the engine. */
const UPLOAD_VIEWS: ReadonlySet<IslandViewName> = new Set(["upload", "uploading", "choose"]);

/** Seconds between the drop and the moment the progress bar starts filling. */
const PRE_PROGRESS = USC.T_PROG_START - USC.T_DROP;

const modeOrder = (m: IslandMode) => (m === "hidden" ? 0 : m === "compact" ? 1 : 2);

export class Island {
  readonly fsm = new IslandStateMachine();
  /** CLOVE on the desktop: his life cycle and the drag out of Clove Notch. */
  readonly desktop: DesktopLink;

  private root: HTMLElement;
  private islandEl!: HTMLElement;
  private clipEl!: HTMLElement;
  private ambientEl!: HTMLElement;
  private contentEl!: HTMLElement;
  private viewsEl!: HTMLElement;
  private botCanvas!: HTMLCanvasElement;
  private botGlow!: HTMLElement;
  private greetingCanvas!: HTMLCanvasElement;
  private miniGrid!: HTMLElement;
  private clockEl!: HTMLElement;
  private clockTimer?: number;
  private countdown!: HTMLElement;
  private wakeStrip!: HTMLElement;

  /** What the compact pill wears for the live activities, and their card. */
  private live = new CompactLive();
  private liveView!: LiveView;
  /** Width the pill's live content asks for, 0 when it wears nothing. */
  private liveWidth = 0;
  private bannerTimer: number | null = null;
  private hoverTimer: number | null = null;
  /** The size the island is animating towards. */
  private aimed = { w: 0, h: 0 };
  /** The next open goes to the live card (a banner, or the bubble). */
  private openOnLive = false;

  private header!: ViewHost;
  private views!: Map<IslandViewName, ViewHost>;
  private uploadCanvas!: UploadCanvas;

  private width = new Tracked(NOTCH_W);
  private height = new Tracked(0);
  private radius = new Tracked(ROUNDED_CORNER);
  private botCx = new Spring(46);
  private botCy = new Spring(16);
  private botSize = new Spring(10);

  private engine = new BotEngine();
  private greeting = new Greeting();
  private greetingShown = false;
  private seasons = new SeasonCache();

  private running = false;
  private lastFrame = 0;
  private dirty = true;
  private canvasPx = 0;
  /** The pixel ratio CLOVE's bitmap was sized for: it changes with the monitor. */
  private canvasDpr = 0;

  // Rust starts the window at full size so the launch greeting has room.
  private collapsed = false;
  private collapseTimer: number | null = null;
  private wasInIsland = false;
  /** A reply is being typed in a card (WhatsApp): Clove Notch stays open. */
  private holdingOpen = false;
  /** Last shape handed to Rust for the click-through test. */
  private pushedRect = { x: -1, y: -1, w: -1, h: -1 };

  // Bot hover → love (IslandWindowController.botHoverIn)
  private botHovering = false;
  private botHoverTimer: number | null = null;
  private lastLoveTime = 0;
  private botHoverStart = { x: 0, y: 0 };

  private confusedRecovery: number | null = null;
  private prevViewBeforeConfused: IslandViewName = "overview";
  private lastSyncedView: IslandViewName | null = null;

  /** The launch greeting ended, or Clove Notch came out of hidden — two of the
   *  moments the Monday recap may open (see src/recap/recap.ts). */
  onGreetingDone: (() => void) | null = null;
  onWake: (() => void) | null = null;

  /** Where a press on CLOVE started: moving past DRAG_THRESHOLD drags him out. */
  private botPress: { x: number; y: number } | null = null;

  /** The next reveal from hidden makes no peek (music starting, as on macOS). */
  private silentReveal = false;

  /** Drop sequence bookkeeping: last tick played, and whether the ✓ has fired. */
  private uploadTens = 0;
  private uploadDone = false;

  constructor(root: HTMLElement) {
    this.root = root;
    this.desktop = new DesktopLink({
      reveal: () => this.reveal(),
      wardrobeFromDesktop: () => this.wardrobeFromDesktop(),
      dizzyFromDesktop: () => this.handleDizzy(),
    });
    this.build();
    this.wireFsm();
    this.wireInput();
    this.engine.onDizzy = () => this.handleDizzy();
    this.greeting.onComplete = () => {
      this.fsm.greetComplete();
      this.onGreetingDone?.();
    };
    State.subscribe(() => {
      this.dirty = true;
      this.ensureRunning();
    });
  }

  /** The request has its answer: the card goes and the session carries on. */
  private closeApproval() {
    State.endApproval();
    this.fsm.pinned = false;
    this.setView(State.defaultView());
  }

  /**
   * Folds a card that is waiting for an answer down to the compact island,
   * without answering it (Mac #290). Nothing is decided: the request keeps
   * waiting, Clove Notch stays on screen, and opening it shows the card again.
   */
  foldApproval() {
    if (!State.pendingApproval || State.mode !== "expanded") return;
    State.isPinned = true;
    this.fsm.pinned = true;
    this.fsm.forcePetit();
  }

  // ── DOM ─────────────────────────────────────────────────────────────────────

  private build() {
    const actions: ViewActions = {
      setView: (v) => this.setView(v),
      cancelDrop: () => this.discardDrop(),
      collapse: () => this.collapse(),
      foldApproval: () => this.foldApproval(),
      setFocus: (id) => {
        State.setFocus(id);
        Sound.play("blip");
        // A pill with a waiting request opens on its card: going back to it
        // after looking at another pill brings the card up again.
        const req = State.pendingApproval;
        if (req?.pillId === id) this.setView(req.questions ? "question" : "approval");
      },
      openTerminal: () => {
        const task = State.focusTask;
        // Sessions from the Claude desktop app live there, not in a terminal.
        if (task?.id === CLAUDE_DESKTOP_ID) void Bridge.openClaudeDesktop();
        else void Bridge.openSession(task?.sessionId ?? null, task?.sessionCwd ?? null);
      },
      // The ↗ button — same targets as openAgentTarget() on macOS.
      tellClove: (text: string) => void Bridge.cloveTell(text),
      flowAction: (action) => void FlowBridge.pillAction(action),
      pickFiles: () => void this.pickFiles(),
      removePill: (id) => {
        const declared = sanitizeDeclared(State.settings, State.os);
        if (!declared.activeIntegrations.includes(id)) return;
        const next = toggleDeclared(declared, id, State.os);
        if (!next) return;
        State.settings.activeIntegrations = next;
        State.loadIntegrationTasks();
        if (State.focusId === id) State.setFocus(State.mainPillId);
        void Bridge.saveSettings(State.settings);
        Sound.play("pop");
        State.notify();
      },
      toggleCloveMic: () => {
        void Bridge.cloveMute("toggle").then((muted) => {
          // No answer: the state shown stays as it was rather than blanking the button.
          if (muted === null) return;
          State.cloveMuted = muted;
          State.notify();
        });
      },
      openTarget: () => {
        const task = State.focusTask;
        if (!task) return;
        const urls: Record<string, string> = {
          integration_resend: "https://resend.com/emails",
          integration_vercel: "https://vercel.com/dashboard",
          integration_github: "https://github.com/pulls",
          integration_stripe: "https://dashboard.stripe.com/payments",
          integration_notion: "https://notion.so",
          integration_calcom: "https://app.cal.com/bookings",
          // No WhatsApp app to bring forward here as on the Mac: WhatsApp Web, in the browser.
          integration_whatsapp: "https://web.whatsapp.com",
        };
        if (task.id === CLAUDE_DESKTOP_ID) void Bridge.openClaudeDesktop();
        else if (task.id === "integration_claude" || task.sessionId) {
          void Bridge.openSession(task.sessionId ?? null, task.sessionCwd ?? null);
        } else if (task.id === "integration_n8n") void Bridge.openN8n();
        else if (task.id === "integration_gitea") void Bridge.openGitea();
        else if (task.id === SPOTIFY_ID) void Bridge.spotifyOpen();
        else if (urls[task.id]) void Bridge.openUrl(urls[task.id]);
      },
      openUrl: (url) => {
        if (url) void Bridge.openUrl(url);
      },
      decide: (d) => {
        const req = State.pendingApproval;
        void Bridge.log(`decide ${d} req=${req?.requestId ?? "none"}`);
        if (!req) return;
        Sound.play(d === "deny" ? "blip" : "approve");
        void Bridge.approvalDecision(req.requestId, d);
        this.closeApproval();
      },
      answer: (answers) => {
        const req = State.pendingApproval;
        if (!req) return;
        Sound.play("approve");
        void Bridge.approvalAnswer(req.requestId, answers);
        this.closeApproval();
      },
      answerInTerminal: () => {
        const req = State.pendingApproval;
        if (!req) return;
        Sound.play("blip");
        void Bridge.approvalDecline(req.requestId);
        this.closeApproval();
      },
      toggleSound: () => {
        State.settings.soundEnabled = !State.settings.soundEnabled;
        Sound.setEnabled(State.settings.soundEnabled);
        // One switch for everything heard: the notch's sounds and CLOVE's own voice.
        void Bridge.cloveSpeech(State.settings.soundEnabled ? "on" : "off");
        void Bridge.saveSettings(State.settings);
        State.notify();
      },
      setVolume: (v) => {
        State.settings.soundVolume = v;
        Sound.setVolume(v);
        void Bridge.saveSettings(State.settings);
        State.notify();
      },
      setAutoClose: (s) => {
        State.settings.autoCloseInterval = s;
        this.fsm.homeToPetitDelay = s;
        void Bridge.saveSettings(State.settings);
        State.notify();
      },
      openSettingsWindow: () => void Bridge.openSettingsWindow(),
      blip: () => Sound.play("blip"),
      chooseOutfit: (selection) => {
        if (parseOutfit(State.settings.mochiOutfit) === selection) return;
        State.settings.mochiOutfit = selection;
        void Bridge.saveSettings(State.settings);
        Sound.play("pop");
        this.engine.triggerEmote("proud");
        State.notify();
      },
      previewOutfit: (outfit) => {
        State.wardrobePreview = outfit;
        State.notify();
      },
      keyboard: (on) => {
        // The chat view manages the keyboard on its own.
        if (on) void Bridge.focusWindow(true);
        else if (State.view !== "prompt" && State.mode === "expanded") void Bridge.focusWindow(false);
      },
      holdOpen: (on) => {
        if (this.holdingOpen === on) return;
        this.holdingOpen = on;
        if (on) {
          this.fsm.pinned = true;
          this.fsm.cancelTimers();
        } else {
          this.fsm.pinned = State.isPinned || State.pendingApproval != null;
          if (!this.fsm.pinned && !this.wasInIsland && this.fsm.state === "home") this.fsm.mouseLeft();
        }
      },
    };

    this.wakeStrip = h("div", { id: "wake-strip" });
    this.botGlow = h("div", { id: "bot-glow" });
    this.botCanvas = h("canvas", { id: "bot-canvas" });
    this.greetingCanvas = h("canvas", { id: "greeting-canvas" });
    this.miniGrid = h("div", { id: "mini-grid" });
    this.clockEl = h("div", { id: "island-clock" });
    this.countdown = h("div", { id: "countdown" });

    this.header = buildHeader(actions);
    this.views = buildViews(actions, () => this.animateGeometry(false));
    this.liveView = buildLive(actions);
    this.views.set("live", this.liveView);
    // The circle beside the pill opens the launcher: timer, memo, status and the rest.
    this.live.bubble.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      if (e.button !== 0) return;
      Sound.resume();
      this.openLauncher();
    });
    this.viewsEl = h("div", { id: "views" });
    for (const v of this.views.values()) this.viewsEl.append(v.el);
    this.contentEl = h("div", { id: "content" }, this.header.el, this.viewsEl);

    // The drop sequence draws the card, the bar and its own CLOVE. It sits under
    // the header, which stays visible on top of it exactly as on macOS.
    this.uploadCanvas = new UploadCanvas({
      ask: () => {
        State.promptContext = State.droppedFile
          ? { kind: "file", name: State.droppedFile.name, path: State.droppedFile.path }
          : null;
        this.setView("prompt");
      },
      cancel: () => this.discardDrop(),
    });

    // Two soft lights in the open page's colour, behind everything: what the frosted panels blur.
    this.ambientEl = h("div", { id: "island-ambient" }, h("i"), h("i"));
    this.clipEl = h(
      "div",
      { id: "island-clip" },
      this.ambientEl,
      this.greetingCanvas,
      this.uploadCanvas.el,
      this.contentEl,
      this.live.el,
    );
    this.islandEl = h(
      "div",
      { id: "island" },
      this.clipEl,
      this.botGlow,
      this.botCanvas,
      this.miniGrid,
      this.clockEl,
      this.countdown,
      this.live.bubble,
    );

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.greetingCanvas.width = Math.round(EXPANDED_W * dpr);
    this.greetingCanvas.height = Math.round(150 * dpr);
    this.greetingCanvas.style.width = `${EXPANDED_W}px`;
    this.greetingCanvas.style.height = "150px";

    // The island's boxes clip and never scroll: a field taking focus (or anything scrolling an element into view)
    // would otherwise shift a whole page up inside the island, out of reach.
    for (const box of [this.clipEl, this.contentEl, this.viewsEl]) {
      box.addEventListener("scroll", () => {
        if (box.scrollTop || box.scrollLeft) {
          box.scrollTop = 0;
          box.scrollLeft = 0;
        }
      });
    }

    this.root.append(this.wakeStrip, this.islandEl);
    this.applyGeometry();
  }

  // ── FSM ─────────────────────────────────────────────────────────────────────

  private wireFsm() {
    this.fsm.homeToPetitDelay = State.settings.autoCloseInterval;
    this.fsm.openOnHover = true;   // a resting pointer opens the bar (or, with the setting on, the page)
    this.fsm.keepVisible = State.settings.keepVisible !== false;
    this.fsm.onTransition = (from, to) => {
      // The greeting is over, however it ended: back to his desktop spot.
      if (from === "clove-notch" && to !== "clove-notch") this.desktop.launch();
      switch (to) {
        case "hidden":
          this.setMode("hidden");
          break;
        case "petit":
          if (from === "clove-notch") this.greeting.interrupt();
          else if (from === "hidden" && !this.silentReveal) Sound.play("peek");
          this.setMode("compact");
          if (from === "clove-notch") State.view = State.defaultView();
          if (!this.wasInIsland) this.fsm.mouseLeft();
          break;
        case "home":
          this.expand(this.openingView());
          if (!this.wasInIsland) this.fsm.mouseLeft();
          // Hooks may have been installed in a terminal since: the idle cards
          // say so on the next open, without polling while Clove Notch is shut.
          void refreshHookPills();
          break;
        case "clove-notch":
          this.expand("greeting");
          this.greeting.start();
          break;
      }
      State.notify();
      if (from === "hidden") this.onWake?.();
    };
  }

  launch() {
    this.fsm.launch();
  }

  // ── Mode / view ─────────────────────────────────────────────────────────────

  private setMode(mode: IslandMode) {
    const prev = State.mode;
    if (mode === prev) return;
    State.mode = mode;
    // The bar a resting pointer opens comes and goes without a sound.
    const quiet = this.fsm.openedByHover || State.view === "bar";
    if (mode === "expanded" && !quiet) Sound.play("open");
    if (prev === "expanded") {
      if (!quiet) Sound.play("close");
      // A folded card is still waiting: it keeps Clove Notch pinned.
      if (!State.pendingApproval) State.isPinned = false;
      void Bridge.focusWindow(false);
    }
    if (mode !== "expanded") {
      this.endBanner(false);
      Live.focusId = null;
      closePlanCard();
      this.engine.resetMorph();
      // Nothing can be seen of the sequence once Clove Notch is shut, and leaving
      // it running would keep the frame loop awake — Clove Notch must cost
      // nothing while hidden.
      UploadSeq.deactivate();
    }
    this.updateWindowCollapsed();
    this.animateGeometry(modeOrder(mode) < modeOrder(prev));
    State.notify();
  }

  /** True while the drop sequence owns Clove Notch body. */
  private get uploadActive(): boolean {
    return State.mode === "expanded" && UploadSeq.isActive && UPLOAD_VIEWS.has(State.view);
  }

  /** Navigating out of the drop flow ends the sequence, as on macOS. */
  private stopSequenceIfLeaving(view: IslandViewName) {
    if (UploadSeq.isActive && !UPLOAD_VIEWS.has(view)) UploadSeq.deactivate();
  }

  expand(view: IslandViewName) {
    this.stopSequenceIfLeaving(view);
    if (view !== "overview") closePlanCard();
    State.view = view;
    if (State.mode !== "expanded") this.setMode("expanded");
    else this.animateGeometry(false);
    State.lastActivity = performance.now();
    State.notify();
  }

  setView(view: IslandViewName) {
    // Asked for by hand: the live view with its dock, not a passing banner.
    if (view === "live") this.endBanner(false);
    this.stopSequenceIfLeaving(view);
    if (view !== "overview") closePlanCard();
    if (State.mode !== "expanded") {
      this.fsm.forceHome();
      State.view = view;
      this.animateGeometry(false);
      State.notify();
      return;
    }
    const grew = VIEW_LAYOUTS[view].height >= VIEW_LAYOUTS[State.view].height;
    State.view = view;
    State.lastActivity = performance.now();
    this.animateGeometry(!grew);
    State.notify();
  }

  collapse() {
    // A waiting card is only ever folded, never dropped by a close.
    if (State.pendingApproval) {
      this.foldApproval();
      return;
    }
    State.isPinned = false;
    this.fsm.pinned = false;
    // Drive the state machine rather than the mode: setting the mode behind its
    // back left it thinking Clove Notch was still open, and a click on the compact
    // island then did nothing — Clove Notch could never be reopened.
    this.fsm.forcePetit();
  }

  /** Alert from the hook server: open on this view. Pinned alerts never auto-close. */
  alert(view: IslandViewName) {
    this.fsm.pinned = State.isPinned;
    this.fsm.forceHome();
    this.expand(view);
  }

  /** A new CLOVE waits and CLOVE has nothing else to say (he is blue). */
  private updateHintOn(): boolean {
    return !State.paused && showsUpdateHint(Updates.waiting(), State.effectiveState, State.pendingApproval != null);
  }

  /**
   * What a click or a hover opens on: while CLOVE is blue, the new version
   * ("CLOVE X is out", Update now); otherwise the usual view. A waiting
   * permission or question always comes first.
   */
  private openingView(): IslandViewName {
    if (this.openOnLive && !State.pendingApproval) return "live";
    // A resting pointer opens only the bar of pages, unless Settings says a hover opens everything.
    if (this.fsm.openedByHover && !State.settings.openOnHover && !State.pendingApproval) return "bar";
    if (this.updateHintOn()) return "update";
    const usual = State.defaultView();
    // Something live and no agent at work: the pill opens on what it is wearing.
    const quiet = State.effectiveState === "idle" || State.effectiveState === "sleeping";
    return Live.size > 0 && quiet && (usual === "overview" || usual === "empty") ? "live" : usual;
  }

  // ── Live activities ─────────────────────────────────────────────────────────

  /** The launcher: start a timer or a memo, see the machine's status. */
  openLauncher() {
    this.liveView.openHub();
    this.openLive(null);
  }

  /** Opens the live view on one activity (null: the most important) and keeps it open. */
  openLive(id: string | null) {
    if (State.paused) return;
    this.endBanner(false);
    Live.focusId = id;
    if (State.mode === "expanded") {
      this.setView("live");
      return;
    }
    this.openOnLive = true;
    this.fsm.forceHome();
    this.openOnLive = false;
  }

  /**
   * Something just happened (a call, a payment, a timer ringing): its card
   * opens by itself for a moment, then the island folds back. Never over a
   * view the user is in, or a request waiting for an answer.
   */
  liveBanner(id: string, ms: number) {
    if (State.paused || State.pendingApproval || !Live.get(id)) return;
    if (State.mode === "expanded" && !(State.view === "live" && this.liveView.banner)) {
      // Already looking at the live view: bring the news to the front there.
      if (State.view === "live") {
        Live.focusId = id;
        this.animateGeometry(false);
        State.notify();
      }
      return;
    }
    Live.focusId = id;
    this.liveView.setBanner(true);
    this.fsm.pinned = true;
    if (State.mode !== "expanded") {
      this.openOnLive = true;
      this.fsm.forceHome();
      this.openOnLive = false;
    } else {
      this.animateGeometry(false);
      State.notify();
    }
    if (this.bannerTimer != null) window.clearTimeout(this.bannerTimer);
    this.bannerTimer = window.setTimeout(() => this.endBanner(true), ms);
  }

  /** The banner is over: fold back (`fold`), or stay open as an ordinary live view. */
  private endBanner(fold: boolean) {
    if (this.bannerTimer != null) window.clearTimeout(this.bannerTimer);
    this.bannerTimer = null;
    if (!this.liveView?.banner) return;
    this.liveView.setBanner(false);
    this.fsm.pinned = State.isPinned || State.pendingApproval != null || this.holdingOpen;
    if (State.mode !== "expanded" || State.view !== "live") return;
    // The pointer is on it: it is being read, so it stays as an ordinary open view.
    if (fold && !this.wasInIsland) {
      Live.focusId = null;
      this.fsm.forcePetit();
    } else {
      this.animateGeometry(false);
      if (!this.wasInIsland) this.fsm.mouseLeft();
      State.notify();
    }
  }

  reveal() {
    this.fsm.reveal();
  }

  /** Music started playing: the compact island, without the peek sound (musicReveal). */
  revealSilently() {
    this.silentReveal = true;
    this.fsm.reveal();
    this.silentReveal = false;
  }

  /** Right-click on CLOVE: wardrobe open ↔ back to the usual view. */
  toggleWardrobe() {
    return;                       // CLOVE has no outfits: right-click does nothing here
    if (State.paused || State.mode === "hidden") return;
    // The greeting and the drop sequence draw a CLOVE of their own.
    if (State.mode === "expanded" && (State.view === "greeting" || this.uploadActive)) return;
    if (State.mode === "expanded" && State.view === "wardrobe") this.setView(State.defaultView());
    else this.setView("wardrobe");
  }

  /**
   * Right-click on the desktop CLOVE (macOS openWardrobeFromDesktop): opens the
   * wardrobe from any state, or goes back if it is already open.
   */
  wardrobeFromDesktop() {
    return;
    this.wardrobeAnywhere();
  }

  /**
   * The wardrobe from any state — compact or hidden island included — or back
   * to the usual view if it is already open. The desktop CLOVE's right-click
   * and the wardrobe shortcut (`open-wardrobe`) both land here.
   */
  wardrobeAnywhere() {
    if (State.mode === "expanded" && State.view === "wardrobe") {
      this.setView(State.defaultView());
      return;
    }
    if (State.paused) return;
    this.alert("wardrobe");
  }

  /** An alert stopped waiting for an answer: let Clove Notch auto-close again. */
  dropPin() {
    this.fsm.pinned = false;
    // The countdown the pin held back starts now, if the mouse is elsewhere.
    if (!this.wasInIsland) this.fsm.mouseLeft();
  }

  // ── Keyboard shortcuts (island/shortcuts.ts) ────────────────────────────────

  emote(name: BotEmoteName) {
    this.engine.triggerEmote(name);
    this.ensureRunning();
  }

  /** Ctrl+P: keep the open island from folding away, or let it fold again. */
  setPinned(on: boolean) {
    State.isPinned = on;
    this.fsm.pinned = on;
    if (on) {
      // The countdown bar reads the state machine's deadline, cleared with it.
      this.fsm.cancelTimers();
    } else if (!this.wasInIsland && this.fsm.state === "home") {
      this.fsm.mouseLeft();
    }
    State.notify();
  }

  /** Clove Notch takes the keyboard, so its own shortcuts work (Mac: makeKey).
   *  It gives it back when it closes, or when the chat is left. */
  takeKeyboard() {
    void Bridge.focusWindow(true);
  }

  /** The desktop shortcut needs a desktop CLOVE: none on GNOME's Wayland. */
  canLeaveIsland(): boolean {
    return this.desktop.supported;
  }

  /** The desktop shortcut (macOS DesktopCLOVEController.flyOutOrHome). */
  flyOutOrHome() {
    // The greeting and the drop sequence draw a CLOVE of their own: he stays
    // for them, as he does for a drag (canDragOut).
    const busy = State.mode === "expanded" && (State.view === "greeting" || this.uploadActive);
    if (busy && !State.mochiOnDesktop) return;
    this.desktop.flyOutOrHome();
  }

  /** Ctrl+O / Ctrl+E go to the view on screen. */
  viewCommand(command: ViewCommand) {
    this.views.get(State.view)?.command?.(command);
  }

  // ── File drop ───────────────────────────────────────────────────────────────

  private onDragDrop(e: { type: string; paths?: string[] }) {
    if (e.type !== "over") void Bridge.log(`drag ${e.type} ${e.paths?.length ?? 0} file(s)`);
    if (State.paused) return;
    switch (e.type) {
      case "enter":
      case "over": {
        if (State.fileDragOver) return;
        State.fileDragOver = true;
        this.engine.animateMorph(1);
        // enterZone must run before Clove Notch expands, so the sequence is
        // already active by the time the view becomes `upload`.
        UploadSeq.enterZone(State.mouseInIsland.x, State.mouseInIsland.y);
        this.alert("upload");
        break;
      }
      case "leave": {
        if (!State.fileDragOver) return;
        State.fileDragOver = false;
        this.engine.animateMorph(0);
        // Clove Notch deliberately stays open: the drag session is still alive.
        UploadSeq.exitZone();
        State.notify();
        break;
      }
      case "drop": {
        State.fileDragOver = false;
        const path = e.paths?.[0];
        LocalSend.dropped = e.paths ?? [];              // all of them, for "Send to …" (LocalSend)
        if (!path) {
          this.engine.animateMorph(0);
          this.setView(State.defaultView());
          return;
        }
        this.swallow(path);
        break;
      }
    }
  }

  /**
   * CLOVE eats the file. Nothing here waits on the file system: the copy into
   * the inbox runs in the background and swaps the path in when it lands, so a
   * slow disk can never stall the animation — same as FileDropHandler on macOS.
   */
  private swallow(path: string) {
    const name = path.split(/[\\/]/).pop() || "file";
    State.droppedFile = { name, path };
    State.promptContext = { kind: "file", name, path };
    State.chatHistory = [];
    void Bridge.chatReset();

    UploadSeq.performDrop(State.uploadDuration);
    this.uploadTens = 0;
    this.uploadDone = false;

    this.engine.gulp();
    Sound.play("approve");
    this.engine.triggerEmote("happy");
    this.engine.animateMorph(0);

    State.uploadProgress = 0;
    this.setView("uploading");
    this.ensureRunning();

    void Bridge.ingestFile(path)
      .then((file) => {
        // Cancelled (or replaced by another drop) while the copy was running.
        if (State.droppedFile?.path !== path) return;
        State.droppedFile = { name: file.name, path: file.path };
        State.promptContext = { kind: "file", name: file.name, path: file.path };
        State.notify();
      })
      .catch((err) => {
        if (State.droppedFile?.path !== path) return;
        UploadSeq.deactivate();
        State.noteMessage = String(err).replace(/^Error:\s*/, "");
        this.engine.animateMorph(0);
        this.setView("note");
        Sound.play("error");
        window.setTimeout(() => this.setView(State.defaultView()), 2400);
      });
  }

  /** CLOVE fork: files chosen in the file chooser (Send, or a double-click on the drop page) go the way of a drop. */
  private picking = false;
  private async pickFiles() {
    if (this.picking) return;
    this.picking = true;
    // The chooser is a window of its own: Clove Notch stays put while it is up.
    const wasPinned = State.isPinned;
    State.isPinned = true;
    this.fsm.pinned = true;
    try {
      const paths = await LocalSend.pick(t("Choose files to send"));
      if (!paths.length) return;
      LocalSend.dropped = paths;
      this.swallow(paths[0]);
    } finally {
      State.isPinned = wasPinned;
      this.fsm.pinned = wasPinned;
      this.picking = false;
    }
  }

  /** "Cancel" on the dropped file: forget it, so the chat does not pick it up. */
  private discardDrop() {
    LocalSend.dropped = [];
    if (LocalSend.progress?.direction === "out") LocalSend.progress = null;
    State.droppedFile = null;
    State.promptContext = null;
    this.setView(State.defaultView());
  }

  /**
   * Sounds and view changes hung off the canvas timeline: a `tick` every 10 %,
   * the ✓ chime when the bar completes, then `choose` once CLOVE has grown back.
   */
  private stepSequence() {
    const since = UploadSeq.sinceDrop();
    if (since == null) return;
    const dur = State.uploadDuration;
    const p = Math.max(0, Math.min(1, (since - PRE_PROGRESS) / dur));

    const tens = Math.floor(p * 10);
    if (tens > this.uploadTens && tens < 10) {
      this.uploadTens = tens;
      Sound.play("tick");
    }

    if (!this.uploadDone && since >= PRE_PROGRESS + dur) {
      this.uploadDone = true;
      Sound.play("approve");
      this.engine.triggerEmote("happy");
    }
    // The extra second is the grow-back, after which the choose card is up.
    if (since >= PRE_PROGRESS + dur + 1 && State.view === "uploading") {
      this.setView("choose");
    }
  }

  // ── Geometry ────────────────────────────────────────────────────────────────

  private targetSize(): { w: number; h: number; r: number } {
    let { w, h } = islandSize(State.mode, State.view, State.chatHistory.length);
    if (State.mode === "expanded" && State.view === "question" && State.pendingApproval?.questions) {
      h = QUESTION_PICKER_H;
    }
    if (State.mode === "expanded" && State.view === "live") {
      ({ w, h } = this.liveView.size());
      // Opened by hand, a card has the header above it like every page; a banner is the card alone.
      if (!this.liveView.banner) {
        w = Math.max(w, this.barWidth());
        h += HEADER_H;
      }
    }
    // A page as wide as what it shows (and its header), not the widest page's width.
    const fit = State.mode === "expanded" ? VIEW_WIDTH[State.view] : undefined;
    if (fit) w = Math.max(fit, this.barWidth());
    if (State.mode === "expanded" && State.view === "bar") w = this.barWidth();
    if (State.mode === "compact") w = this.pillWidth();
    // Never rounder than a pill: a short card keeps its ends round, not pointed.
    const r = Math.min(State.mode === "expanded" ? EXPANDED_CORNER : ROUNDED_CORNER, h / 2);
    return { w, h, r };
  }

  /** The colour of the light behind the glass: the open page's, or the activity or session in front. */
  private glowColor(): string {
    switch (State.view) {
      case "live": {
        const a = this.liveView.hubShown ? null : Live.focused(Date.now());
        return a ? accentOf(a) : "#fb923c";
      }
      case "overview":
      case "empty": return State.focusTask?.color ?? "#5e5ce6";
      case "controls": return "#64d2ff";
      case "time": return "#ff9f0a";
      case "prompt": return "#fb923c";
      case "upload":
      case "uploading":
      case "choose": return "#30d158";
      case "approval": return "#f5a524";
      case "question": return "#22d3ee";
      case "error": return "#f4505e";
      case "finished": return "#34d399";
      default: return "#5e5ce6";
    }
  }

  /** The bar is as wide as what the header holds: its tabs, the unread chips, its buttons. */
  private barWidth(): number {
    // Each part's full width, even where the island is still too narrow to show it (scrollWidth).
    let w = 36;
    for (const part of Array.from(this.header.el.children) as HTMLElement[]) w += Math.max(part.offsetWidth, part.scrollWidth) + 10;
    return clamp(w, 300, EXPANDED_W);
  }

  /** Room at the pill's right end for unread messages or the muted mic (syncCompactStatus). */
  private statusWidth(): number {
    return this.miniGrid.childElementCount > 0 ? 34 : 0;
  }

  /** The pill: wide enough for CLOVE's mark and both sides of the live activity. */
  private pillWidth(): number {
    if (this.liveWidth <= 0) return (State.settings.showClock ? COMPACT_CLOCK_W : COMPACT_W) + this.statusWidth();
    // 38 for the mark, 26 between the two sides, 14 at the right end.
    // The width he picked in Settings is how wide the pill may grow.
    return clamp(38 + this.liveWidth + 26 + 14 + this.statusWidth(), COMPACT_W, compactWidth() || COMPACT_MAX_W);
  }

  private animateGeometry(shrinking: boolean) {
    const { w, h, r } = this.targetSize();
    this.aimed = { w, h };
    if (shrinking) {
      this.width.curveTowards(w);
      this.height.curveTowards(h);
      this.radius.curveTowards(r);
    } else {
      this.width.springTo(w);
      this.height.springTo(h);
      this.radius.springTo(r);
    }
    this.ensureRunning();
  }

  private applyGeometry() {
    const w = this.width.value;
    const hh = this.height.value;
    const r = this.radius.value;
    this.islandEl.style.width = `${w}px`;
    this.islandEl.style.height = `${hh}px`;
    this.islandEl.style.borderRadius = `${Math.min(r, hh / 2)}px`;
    this.islandEl.style.transform = `translateX(-50%)`;
    // Retracted, the pill slides up into the edge it floats under.
    this.islandEl.style.top = `${hh < 1 ? 0 : TOP_GAP}px`;
    this.islandEl.classList.toggle("gone", hh < 1);
    this.live.el.style.right = `${12 + this.statusWidth()}px`;
    this.live.bubble.style.left = `${w + BUBBLE_GAP}px`;
    // Level with the pill, and with the bar it opens into: centred on whichever is there.
    this.live.bubble.style.top = `${Math.min(8, Math.max(0, (hh - BUBBLE) / 2))}px`;
    // These follow Clove Notch as it resizes, so they belong here rather than in
    // the state-driven DOM sync.
    this.miniGrid.style.left = `${w - 29 - 12}px`;
    this.miniGrid.style.top = `${hh / 2 - 14.5}px`;
    this.clockEl.style.height = `${hh}px`;
    this.greetingCanvas.style.left = `${(w - EXPANDED_W) / 2}px`;
    this.uploadCanvas.el.style.left = `${(w - EXPANDED_W) / 2}px`;

    const rect = this.hitRect();
    const p = this.pushedRect;
    if (Math.abs(p.x - rect.x) > 0.5 || Math.abs(p.w - rect.w) > 0.5 || Math.abs(p.h - rect.h) > 0.5) {
      this.pushedRect = rect;
      void Bridge.setIslandRect(rect.x, rect.y, rect.w, rect.h);
    }
  }

  /** Island rect in window coordinates (origin top-left of the 720×320 window). */
  private islandRect(): { x: number; y: number; w: number; h: number } {
    const w = this.width.value;
    const hh = this.height.value;
    const viewportW = window.innerWidth > 0 ? window.innerWidth : PANEL_W;
    return { x: (viewportW - w) / 2, y: hh < 1 ? 0 : TOP_GAP, w, h: hh };
  }

  /**
   * What takes the mouse: the island, the gap above it (the pointer thrown at
   * the top edge still lands on it) and the bubble beside it.
   */
  /** The circle is there beside the pill and beside the bar the pill opens into, not beside a page. */
  private bubbleShown(): boolean {
    return State.mode === "compact" || (State.mode === "expanded" && State.view === "bar");
  }

  private hitRect(): { x: number; y: number; w: number; h: number } {
    const r = this.islandRect();
    const bubble = this.bubbleShown() ? BUBBLE_GAP + BUBBLE : 0;
    return { x: r.x, y: 0, w: r.w + bubble, h: r.h + r.y };
  }

  // ── Window collapse (hidden → tiny wake strip, zero polling) ────────────────

  private updateWindowCollapsed() {
    if (this.collapseTimer != null) {
      window.clearTimeout(this.collapseTimer);
      this.collapseTimer = null;
    }
    if (State.mode === "hidden") {
      // Let Clove Notch finish retracting, then drop the window to the wake strip:
      // from there the OS delivers no cursor events, so nothing polls at all.
      this.collapseTimer = window.setTimeout(() => {
        this.collapseTimer = null;
        if (State.mode !== "hidden") return;
        this.collapsed = true;
        void Bridge.setCollapsed(true);
      }, 420);
    } else if (this.collapsed) {
      // Grow the window back before Clove Notch animates open.
      this.collapsed = false;
      void Bridge.setCollapsed(false);
    }
  }

  // ── Input ───────────────────────────────────────────────────────────────────

  private wireInput() {
    // The wake strip is the only thing the OS can hit while Clove Notch is hidden.
    this.wakeStrip.addEventListener("mouseenter", () => {
      Sound.resume();
      if (State.mode === "hidden") this.fsm.mouseEntered();
    });

    this.islandEl.addEventListener("mousedown", (e) => {
      Sound.resume();
      State.lastActivity = performance.now();
      // A click on the bar itself, not on one of its buttons, opens what the pill would have.
      const onBar = State.mode === "expanded" && State.view === "bar";
      // A click makes a hover-opened island an ordinary open one.
      this.fsm.userInteracted();
      if (onBar && e.button === 0 && !(e.target as HTMLElement).closest("button")) {
        this.setView(this.openingView());
        return;
      }
      // And a banner someone reaches for stays, with its dock.
      this.endBanner(false);
      // A press on CLOVE may become a drag out to the desktop.
      if (e.button === 0 && this.isBotHit(e.clientX, e.clientY)) {
        this.botPress = { x: e.clientX, y: e.clientY };
      }
      // Right-click on CLOVE opens the wardrobe, and closes it again.
      if (e.button === 2 && this.isBotHit(e.clientX, e.clientY)) {
        this.cancelBotHover();
        this.toggleWardrobe();
        return;
      }
      if (State.mode !== "expanded") {
        this.fsm.click();
        return;
      }
      if (this.isBotHit(e.clientX, e.clientY)) {
        this.cancelBotHover();
        this.engine.slap();
      }
    });

    // No browser menu over CLOVE: his right-click is the wardrobe. Everywhere
    // else (the chat field) the webview keeps its own menu.
    this.islandEl.addEventListener("contextmenu", (e) => {
      if (this.isBotHit(e.clientX, e.clientY)) e.preventDefault();
    });

    // Dragging CLOVE out of Clove Notch puts him on the desktop.
    window.addEventListener("mousemove", (e) => {
      if (this.desktop.carrying) {
        this.desktop.carry(e.clientX, e.clientY);
        return;
      }
      const press = this.botPress;
      if (!press) return;
      if (!(e.buttons & 1)) {
        this.botPress = null;
        return;
      }
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) <= DRAG_THRESHOLD) return;
      this.botPress = null;
      if (!this.canDragOut()) return;
      this.cancelBotHover();
      this.desktop.pickUp(e.clientX, e.clientY);
    });
    window.addEventListener("mouseup", (e) => {
      this.botPress = null;
      if (this.desktop.carrying) this.desktop.carryEnd(e.clientX, e.clientY);
    });

    // Only keys typed into Clove Notch itself land here, never Escape typed in
    // a terminal — so it may fold a waiting card away, as Escape in the notch
    // does on macOS.
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && State.mode === "expanded") {
        if (State.pendingApproval) this.foldApproval();
        else if (!State.isPinned) this.collapse();
      }
      State.lastActivity = performance.now();
    });

    void onDragDrop((e) => this.onDragDrop(e));

    // Outside Tauri (plain browser) drive the cursor from DOM events so the
    // island can be inspected with `npm run dev`.
    if (!IS_TAURI) this.followPageCursor();
  }

  /**
   * Takes the cursor from the page's own mouse events instead of Rust's poll.
   * Used where the OS has no global cursor position (Wayland): the events only
   * fire while the pointer is over Clove Notch, so leaving the window is
   * reported as a cursor far away, which is what the poll would have said.
   */
  followPageCursor() {
    window.addEventListener("mousemove", (e) => this.onCursor(e.clientX, e.clientY));
    window.addEventListener("mouseout", (e) => {
      if (e.relatedTarget == null) this.onCursor(-10_000, -10_000);
    });
  }

  /**
   * Pointer on/off Clove Notch as the compositor sees it (Linux only). Null
   * until the first report, so a platform that never sends it is not gated.
   */
  private pointerInside: boolean | null = null;

  setPointerInside(inside: boolean) {
    this.pointerInside = inside;
  }

  /** CLOVE fork: he clicked somewhere else: fold to compact, unless he's on Clove Notch or typing in it. */
  focusElsewhere() {
    if (State.mode !== "expanded" || State.isPinned || this.pointerInside === true || this.wasInIsland) return;
    const typing = document.activeElement instanceof HTMLInputElement || document.activeElement instanceof HTMLTextAreaElement;
    if (typing || State.pendingApproval) return;
    this.collapse();
  }

  /** Cursor in window-logical coordinates. */
  onCursor(x: number, y: number) {
    // WebKitGTK can deliver a mousemove after the pointer has left the layer
    // surface; trusting it re-enters Clove Notch and the auto-close never runs.
    if (this.pointerInside === false) {
      x = -10_000;
      y = -10_000;
    }
    State.mouse = { x, y };
    const island = this.islandRect();
    State.mouseInIsland = { x: x - island.x, y: y - island.y };
    const rect = this.hitRect();

    // Windows sends no cursor position with an OLE drag, so the drop sequence is
    // fed from the Win32 cursor poll instead — it runs throughout the drag.
    if (UploadSeq.isActive && !UploadSeq.dropped) {
      UploadSeq.updateCursor(State.mouseInIsland.x, State.mouseInIsland.y);
    }

    const inIsland =
      x >= rect.x - HIT_MARGIN && x <= rect.x + rect.w + HIT_MARGIN &&
      y >= rect.y - HIT_MARGIN && y <= rect.y + rect.h + HIT_MARGIN;

    // Recorded before the state machine hears of it: a transition it makes
    // right away (open on hover) reads where the pointer is, and must not see
    // the pointer as still outside.
    const wasIn = this.wasInIsland;
    this.wasInIsland = inIsland;
    if (inIsland && !wasIn) {
      if (this.fsm.state === "clove-notch") this.greeting.hover();
      // A pointer only passing under the top edge opens nothing: it has to rest a moment.
      if (this.hoverTimer != null) window.clearTimeout(this.hoverTimer);
      this.hoverTimer = window.setTimeout(() => {
        this.hoverTimer = null;
        if (this.wasInIsland) this.fsm.mouseEntered();
      }, State.mode === "compact" ? 140 : 0);
    }
    if (!inIsland && wasIn) {
      if (this.hoverTimer != null) {
        // It left before it had rested: as if it had never come.
        window.clearTimeout(this.hoverTimer);
        this.hoverTimer = null;
      } else {
        this.fsm.mouseLeft();
      }
    }

    // Bot hover → love
    const overBot = State.mode === "expanded" && State.stateOverride == null && this.isBotHit(x, y);
    if (overBot && !this.botHovering) this.botHoverIn(x, y);
    if (!overBot && this.botHovering) this.cancelBotHover();
    this.botHovering = overBot;
    if (this.botHovering) {
      const d = Math.hypot(x - this.botHoverStart.x, y - this.botHoverStart.y);
      if (d > 40) {
        this.botHoverStart = { x, y };
        this.scheduleLove();
      }
    }

    this.ensureRunning();
  }

  /** The greeting and the drop sequence draw a CLOVE of their own: not that one. */
  private canDragOut(): boolean {
    if (State.mode === "hidden" || !this.desktop.canPickUp()) return false;
    return !(State.mode === "expanded" && (State.view === "greeting" || this.uploadActive));
  }

  private isBotHit(x: number, y: number): boolean {
    // Out on the desktop, Clove Notch's CLOVE is invisible: nothing to hit.
    if (State.mochiOnDesktop || State.mode === "expanded") return false;
    const rect = this.islandRect();
    const cx = rect.x + this.botCx.value;
    const cy = rect.y + this.botCy.value;
    const radius = this.botSize.value / 2;
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius;
  }

  private botHoverIn(x: number, y: number) {
    if (performance.now() / 1000 - this.lastLoveTime < 6) return;
    this.botHoverStart = { x, y };
    this.engine.blink();
    this.engine.tgEs = 1.08;
    Sound.play("hover");
    this.scheduleLove();
  }

  private scheduleLove() {
    if (this.botHoverTimer != null) window.clearTimeout(this.botHoverTimer);
    this.botHoverTimer = window.setTimeout(() => {
      this.botHoverTimer = null;
      if (!this.botHovering || State.stateOverride != null) return;
      if (performance.now() / 1000 - this.lastLoveTime < 6) return;
      this.lastLoveTime = performance.now() / 1000;
      this.engine.triggerEmote("love");
      Sound.play("love");
    }, 1900);
  }

  private cancelBotHover() {
    if (this.botHoverTimer != null) window.clearTimeout(this.botHoverTimer);
    this.botHoverTimer = null;
    this.engine.tgEs = 1;
  }

  /** Three slaps → dizzy + confused view for 3.3 s, then back. */
  handleDizzy() {
    this.prevViewBeforeConfused = State.view;
    State.stateOverride = "dizzy";
    this.engine.setState("dizzy");
    Sound.play("dizzy");
    this.alert("confused");
    if (this.confusedRecovery != null) window.clearTimeout(this.confusedRecovery);
    this.confusedRecovery = window.setTimeout(() => {
      this.confusedRecovery = null;
      State.stateOverride = null;
      this.engine.setState(State.effectiveState);
      if (State.view === "confused") {
        const fallback = State.defaultView();
        this.setView(this.prevViewBeforeConfused === "confused" ? fallback : this.prevViewBeforeConfused);
      }
      this.engine.triggerEmote("happy");
    }, 3300);
  }

  // ── Frame loop ──────────────────────────────────────────────────────────────

  ensureRunning() {
    if (this.running) return;
    this.running = true;
    this.lastFrame = performance.now();
    requestAnimationFrame(this.frame);
  }

  private frame = (nowMs: number) => {
    const dt = Math.min(0.05, (nowMs - this.lastFrame) / 1000);
    this.lastFrame = nowMs;

    this.width.step(dt, nowMs);
    this.height.step(dt, nowMs);
    this.radius.step(dt, nowMs);
    this.applyGeometry();

    if (this.dirty) {
      this.dirty = false;
      this.syncDom();
    }

    this.updateBotTargets();
    this.botCx.step(dt);
    this.botCy.step(dt);
    this.botSize.step(dt);

    const greetingActive = State.mode === "expanded" && State.view === "greeting";
    if (greetingActive) {
      const gctx = this.greetingCanvas.getContext("2d");
      if (gctx) {
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        if (this.greetingCanvas.width !== Math.round(EXPANDED_W * dpr)) {
          this.greetingCanvas.width = Math.round(EXPANDED_W * dpr);
          this.greetingCanvas.height = Math.round(150 * dpr);
        }
        gctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.greeting.draw(gctx);
      }
    } else {
      // Kept running even while the drop canvas is up, so Clove Notch's own CLOVE
      // is already in the right place the moment the canvas fades out.
      this.drawBot(dt);
    }

    const uploadActive = this.uploadActive;
    if (uploadActive) this.uploadCanvas.draw(UploadSeq.frame(), nowMs / 1000);
    this.uploadCanvas.el.classList.toggle("on", uploadActive);
    this.viewsEl.classList.toggle("hidden-by-upload", uploadActive);

    tickMiniBots(dt);
    // A ticker scroll that loses its frames freezes mid-way, rows overlapping.
    const viewAnimating = this.views.get(State.view)?.tick?.(nowMs) === true;
    if (UploadSeq.isActive) this.stepSequence();
    this.updateCountdown(nowMs);

    // Nothing is drawn while Clove Notch is hidden, so nothing may keep the loop
    // alive either. This used to read `... || this.engine.busy || State.mode !==
    // "hidden"`, and engine.busy is permanently true for any state with a
    // looping animation — breathing, ratelimit sweat, sleeping z's, the search
    // sweep — so a hidden island went on burning frames in exactly the states it
    // spends most of its life in. Geometry still has to finish retracting.
    const settling =
      this.width.animating || this.height.animating || this.radius.animating;
    const busy = State.mode === "hidden"
      ? settling
      : settling ||
        !this.botCx.settled || !this.botCy.settled || !this.botSize.settled ||
        greetingActive || this.engine.busy || UploadSeq.isActive || viewAnimating;

    if (busy) {
      requestAnimationFrame(this.frame);
    } else {
      this.running = false;
      Sound.idle();
    }
  };

  private updateBotTargets() {
    const p = botPosition(State.mode, State.view, this.height.value, State.uploadProgress);
    // Alone in the pill, the mark sits in its middle.
    const alone = State.mode === "compact" && this.liveWidth <= 0 && !State.settings.showClock;
    this.botCx.target = alone ? this.aimed.w / 2 : p.cx;
    this.botCy.target = p.cy;
    this.botSize.target = p.diameter / 0.6;

    const greetingActive = State.mode === "expanded" && State.view === "greeting";
    // The drop canvas draws its own CLOVE; two of them would overlap. Out on the
    // desktop, he isn't here at all.
    const away = State.mochiOnDesktop;
    // Open, the island is its content: CLOVE's mark lives in the pill only.
    const visible = p.opacity > 0 && State.mode !== "expanded" && !greetingActive && !this.uploadActive && !away;
    this.botCanvas.style.opacity = visible ? "1" : "0";

    this.botGlow.style.display = "none";
  }

  private drawBot(dt: number) {
    const size = this.botSize.value;
    const w = Math.max(1, Math.round(size));
    const hCss = w + BOT_OVERHANG;
    const wCss = w + BOT_SIDE * 2;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    // Drawn at the current ratio, so a bitmap sized for another monitor's
    // would show CLOVE too big and cut, or too small.
    if (this.canvasPx !== w || this.canvasDpr !== dpr) {
      this.canvasPx = w;
      this.canvasDpr = dpr;
      this.botCanvas.width = Math.round(wCss * dpr);
      this.botCanvas.height = Math.round(hCss * dpr);
      this.botCanvas.style.width = `${wCss}px`;
      this.botCanvas.style.height = `${hCss}px`;
    }
    this.botCanvas.style.left = `${this.botCx.value - wCss / 2}px`;
    this.botCanvas.style.top = `${this.botCy.value - BOT_OVERHANG / 2 - hCss / 2}px`;

    const ctx = this.botCanvas.getContext("2d");
    if (!ctx) return;

    const focus = State.focusTask;
    // A new CLOVE waits: over an idle or sleeping CLOVE, the blue and the arrow
    // badge (whats-new.ts). Anything CLOVE has to say comes first.
    this.engine.setUpdateHint(this.updateHintOn() ? UPDATE_BLUE_RGB : null);
    // While a plan card is open CLOVE wears the plan's colour, like its pill.
    this.engine.bodyColor = planCardOpen()
      ? hexToRGB(openPlanColor())
      : this.engine.showsUpdateHint
        ? UPDATE_BLUE_RGB
        : focus?.isIntegration
          ? hexToRGB(focus.color)
          : null;
    this.engine.particleOverhang = BOT_OVERHANG;
    this.engine.lookX = this.lookX();
    this.engine.lookY = this.lookY();
    if (this.engine.morph > 0.3) {
      this.engine.slotHTarget = State.fileDragOver ? 0.2 : 0;
    } else {
      this.engine.slotHTarget = 0;
      if (this.engine.morph < 0.05) {
        this.engine.slotH = 0;
        this.engine.slotHVel = 0;
      }
    }
    // Only the main CLOVE is dressed — the one of the main tool's pill (Settings →
    // Active pills): a focused integration pill shows its own colours, unless
    // the wardrobe is open (BotCanvasView.showOutfit, macOS).
    // In the wardrobe the hovered outfit swaps in at once, without the drop-in.
    const inWardrobe = State.mode === "expanded" && State.view === "wardrobe";
    const mainFocused = State.focusId == null || State.focusId === State.mainPillId;
    const showOutfit = mainFocused || State.mode !== "expanded" || inWardrobe;
    const outfit = State.wardrobePreview ?? this.seasons.get(parseOutfit(State.settings.mochiOutfit));
    this.engine.setOutfit(showOutfit ? outfit : "none", !inWardrobe);
    // Dances while music plays: always in the compact island, expanded only on
    // the music pill's card (BotCanvasView, macOS). Asked every frame.
    this.engine.setDancing(islandDances({
      music: State.spotifyPlaying,
      state: State.effectiveState,
      mode: State.mode,
      view: State.view,
      focusId: State.focusTask?.id,
    }));

    this.engine.update(dt);
    ctx.setTransform(dpr, 0, 0, dpr, BOT_SIDE * dpr, 0);
    ctx.clearRect(-BOT_SIDE, 0, wCss, hCss);
    ctx.save();
    this.engine.applyDance(ctx, w, hCss);
    this.engine.draw(ctx, w, hCss);
    ctx.restore();
  }

  /** BotCanvasView.lookX / lookY — tanh of the distance to the bot. */
  private lookX(): number {
    const rect = this.islandRect();
    const botScreenX = rect.x + this.botCx.value;
    return Math.tanh((State.mouse.x - botScreenX) / 260);
  }

  private lookY(): number {
    return -Math.tanh((State.mouse.y - this.botCy.value) / 200);
  }

  private updateCountdown(nowMs: number) {
    // The state machine's own deadline, so the bar follows an auto-close delay
    // edited while the countdown runs.
    const dueAt = this.fsm.homeCollapseDueAt;
    if (State.mode !== "expanded" || State.isPinned || dueAt == null) {
      this.countdown.style.width = "0px";
      return;
    }
    const autoClose = this.fsm.homeToPetitDelay;
    const windowS = Math.min(10, autoClose * 0.6);
    const remaining = (dueAt - nowMs) / 1000;
    this.countdown.style.width =
      remaining < windowS ? `${Math.max(0, clamp(remaining / windowS, 0, 1) * 160)}px` : "0px";
  }

  // ── DOM sync ────────────────────────────────────────────────────────────────

  private syncDom() {
    const expanded = State.mode === "expanded";
    const greetingActive = expanded && State.view === "greeting";

    const live = expanded && !greetingActive;
    this.contentEl.style.opacity = live ? "1" : "0";
    // While the drop sequence owns the body its buttons are painted on the canvas
    // underneath, so only the header may keep taking clicks up here.
    this.contentEl.style.pointerEvents = live && !this.uploadActive ? "auto" : "none";
    this.header.el.style.pointerEvents = live ? "auto" : "none";
    this.greetingCanvas.style.display = greetingActive ? "block" : "none";

    // Leaving the greeting, however it ends, lets its sound fade out.
    if (this.greetingShown && !greetingActive) this.greeting.leave();
    this.greetingShown = greetingActive;
    // A wardrobe try-on never outlives the wardrobe.
    if (State.wardrobePreview && !(expanded && State.view === "wardrobe")) State.wardrobePreview = null;

    this.islandEl.classList.toggle("expanded", expanded);
    this.islandEl.dataset.view = expanded ? State.view : State.mode;
    const glow = this.glowColor();
    if (this.islandEl.style.getPropertyValue("--glow") !== glow) this.islandEl.style.setProperty("--glow", glow);
    this.header.sync();
    // The header is on every page; only a banner (a card that came up by itself) goes without it.
    this.header.el.style.display = State.view === "live" && this.liveView.banner ? "none" : "";
    if (!(expanded && State.view === "live")) this.liveView.resetClicks();
    for (const [name, view] of this.views) {
      const on = name === State.view;
      view.el.classList.toggle("on", on);
      if (on) view.sync();
    }

    // The chat is the only view with a text field, so it is the only time the
    // island is allowed to take keyboard focus.
    if (this.lastSyncedView !== State.view) {
      const wasChat = this.lastSyncedView === "prompt";
      this.lastSyncedView = State.view;
      if (State.view === "prompt") {
        void Bridge.focusWindow(true);
        window.setTimeout(() => this.views.get("prompt")?.focus?.(), 120);
      } else if (wasChat) {
        void Bridge.focusWindow(false);
      }
    }

    // The pill's live content, measured so the pill fits it; the card resizes with what it shows.
    const compact = State.mode === "compact";
    this.live.el.classList.toggle("on", compact);
    this.live.bubble.classList.toggle("shown", this.bubbleShown());
    this.live.setBubble(this.unread());
    const liveWidth = this.live.sync(Date.now());
    if (Math.abs(liveWidth - this.liveWidth) > 0.5) {
      this.liveWidth = liveWidth;
      if (compact) this.animateGeometry(false);
    }
    // An open page follows what it shows: a card that changed, an unread chip that widened the header.
    if (expanded) {
      const want = this.targetSize();
      if (Math.abs(want.w - this.aimed.w) > 0.5 || Math.abs(want.h - this.aimed.h) > 0.5) {
        this.animateGeometry(want.w < this.aimed.w && want.h <= this.aimed.h);
      }
    }

    // Compact mini grid
    // The right end of the pill: unread messages, or the muted mic.
    const showGrid = State.mode === "compact";
    this.miniGrid.style.opacity = showGrid ? "1" : "0";
    if (showGrid) this.syncCompactStatus();

    this.updateClock();

    syncMiniBotStates(State.tasks);
    this.engine.setState(State.effectiveState);
  }

  /** The clock sits in the middle of the compact island, where the notch is on a Mac. CLOVE fork: while something
   *  runs (a timer, a recording, music…), its live activity takes the clock's place, like a Dynamic Island. */
  private updateClock() {
    const on = State.mode === "compact" && State.settings.showClock && !this.live.active;
    this.clockEl.style.opacity = on ? "1" : "0";
    if (!on) return;
    const now = new Date();
    const date = now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
    const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const text = `${date}  ${time}`;
    if (this.clockEl.textContent !== text) this.clockEl.textContent = text;
  }

  /**
   * CLOVE fork: the pill's right end, in place of the four little mascots: a red mic while CLOVE is muted.
   * Unread messages are in the circle beside the pill (unread, below).
   */
  private syncCompactStatus() {
    const key = State.cloveMuted === true ? "muted" : "idle";
    if (this.miniGrid.dataset.key === key) return;
    this.miniGrid.dataset.key = key;
    this.miniGrid.className = `status status-${key}`;
    this.miniGrid.replaceChildren();
    pruneMiniBots();
    if (key === "muted") this.miniGrid.append(svg(ICONS.micOff, 15));
    // The pill's two sides stop short of it, and the pill makes room.
    this.live.el.style.right = `${12 + this.statusWidth()}px`;
    if (State.mode === "compact") this.animateGeometry(false);
  }

  /** The app with unread messages (the newest first) and how many in all: the circle beside the pill shows it. */
  private unread(): { logo?: string; letter: string; count: number } | null {
    const unread = Object.entries(State.cloveUnread).filter(([, n]) => n > 0);
    if (!unread.length) return null;
    const newest = [...State.cloveLog].reverse().find((x) => x.kind === "message" && (State.cloveUnread[x.app] ?? 0) > 0);
    const app = newest?.app ?? unread[0][0];
    return { logo: APP_LOGOS[app], letter: app.slice(0, 1).toUpperCase(), count: unread.reduce((n, [, c]) => n + c, 0) };
  }

  /** Keep Clove Notch on screen: never let the compact island hide itself, and bring it back if it had. */
  private applyKeepVisible() {
    this.fsm.keepVisible = State.settings.keepVisible !== false;
    if (this.fsm.keepVisible && !State.paused && this.fsm.state === "hidden") this.fsm.reveal();
    else if (this.fsm.keepVisible && this.fsm.state === "petit") this.fsm.cancelTimers();
  }

  /** Applies settings coming from Rust at boot. */
  applySettings() {
    Sound.setEnabled(State.settings.soundEnabled);
    Sound.setVolume(State.settings.soundVolume);
    this.fsm.homeToPetitDelay = State.settings.autoCloseInterval;
    this.fsm.openOnHover = true;   // a resting pointer opens the bar (or, with the setting on, the page)
    setCompactWidth(State.settings.compactWidth ?? 0);
    this.applyKeepVisible();
    State.notify();
    // ponytail: one timer for the life of the window; a minute is the clock's finest tick.
    this.clockTimer ??= window.setInterval(() => this.updateClock(), 10_000);
  }

  get panelSize() {
    return { w: PANEL_W, h: PANEL_H };
  }

  get chatHeight() {
    return chatPromptHeight(State.chatHistory.length);
  }
}

// (English only for now: these strings are not in the translation tables yet.)
// To-dos, reminders and the calendar's events on the notch. They belong to the
// CLOVE assistant (assistant/agenda.py), which keeps them and says a reminder
// when it is due: here they are only shown and changed, over its control
// socket, so what is added by hand can be changed by voice and the other way
// round. The panel on the Controls page lists them; the calendar's day panel
// shows one day.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "../core/bridge";
import { State } from "../core/state";
import { h } from "../views/dom";
import { icon } from "./icons";

export interface Todo { id: number; text: string; due: string }
export interface Reminder { id: number; text: string; at: number }
export interface CalEvent { title: string; day: string; time: string; end: string; where: string }

interface Snapshot {
  ok: boolean;
  say: string;
  todos: Todo[];
  reminders: Reminder[];
  events: CalEvent[];
  calendar: boolean;
  calendarError: string;
  month: string;
}

/** YYYY-MM-DD of a local day. */
export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const monthKey = (d: Date) => dayKey(d).slice(0, 7);

class AgendaState {
  todos: Todo[] = [];
  reminders: Reminder[] = [];
  events: CalEvent[] = [];
  calendar = false;
  month = "";
  /** Why the last change did not happen, or that CLOVE is not there to keep them. */
  error = "";
  /** Changes with every answer: views redraw when it does. */
  version = 0;
  private asked = 0;
  private wanted = monthKey(new Date());

  private apply(s: Snapshot) {
    this.todos = s.todos ?? [];
    this.reminders = s.reminders ?? [];
    this.events = s.events ?? [];
    this.calendar = s.calendar === true;
    this.month = s.month ?? "";
    this.error = s.ok ? s.calendarError ?? "" : s.say.replace(/^error:\s*/, "");
    this.version++;
    State.notify();
  }

  /** One request to the assistant; its answer is the new state. */
  async request(op: Record<string, unknown>): Promise<boolean> {
    this.asked = Date.now();
    if (!IS_TAURI) {
      this.error = "Tasks need Clove Notch running as an app.";
      this.version++;
      State.notify();
      return false;
    }
    try {
      const line = await invoke<string>("clove_agenda", { request: JSON.stringify({ month: this.wanted, ...op }) });
      // A CLOVE from before tasks and reminders answers with its list of commands, not JSON.
      const s = (line.trim().startsWith("{") ? JSON.parse(line) : null) as Snapshot | null;
      if (!s || !Array.isArray(s.todos)) throw new Error("This CLOVE is older than tasks and reminders: update it to keep them here.");
      this.apply(s);
      return s.ok;
    } catch (err) {
      this.error = String(err).replace(/^Error:\s*/, "");
      this.version++;
      State.notify();
      return false;
    }
  }

  /** Reads again when what is shown is older than a minute, or is another month. */
  refresh(month?: Date, force = false) {
    const want = month ? monthKey(month) : this.wanted;
    const stale = Date.now() - this.asked > 60_000;
    if (!force && !stale && want === this.wanted) return;
    this.wanted = want;
    void this.request({ op: "list" });
  }

  /** What falls on a day: the calendar's events, the reminders due, the to-dos dated for it. */
  on(day: Date): { events: CalEvent[]; reminders: Reminder[]; todos: Todo[] } {
    const key = dayKey(day);
    return {
      events: this.events.filter((e) => e.day === key),
      reminders: this.reminders.filter((r) => dayKey(new Date(r.at)) === key),
      todos: this.todos.filter((t) => t.due === key),
    };
  }

  /** Days of a month that have something on them (for the dots under the dates). */
  busyDays(month: Date): Set<number> {
    const prefix = monthKey(month);
    const days = new Set<number>();
    for (const e of this.events) if (e.day.startsWith(prefix)) days.add(Number(e.day.slice(8)));
    for (const r of this.reminders) {
      const k = dayKey(new Date(r.at));
      if (k.startsWith(prefix)) days.add(Number(k.slice(8)));
    }
    for (const t of this.todos) if (t.due.startsWith(prefix)) days.add(Number(t.due.slice(8)));
    return days;
  }
}

export const Agenda = new AgendaState();

// ── Pieces ────────────────────────────────────────────────────────────────────

/** A change that didn't happen: the field shakes once, and says why when hovered. */
function refused(input: HTMLInputElement) {
  input.title = Agenda.error;
  input.classList.remove("shake");
  void input.offsetWidth;
  input.classList.add("shake");
}

const div = (cls: string, ...children: (Node | string | null)[]) => h("div", { class: cls }, ...children);

interface FieldHost {
  keyboard(on: boolean): void;
  holdOpen(on: boolean): void;
}

function field(host: FieldHost, placeholder: string, cls: string, onEnter: () => void): HTMLInputElement {
  const input = h("input", { class: `ag-input ${cls}`, type: "text", placeholder, spellcheck: "false" });
  input.addEventListener("focus", () => { host.keyboard(true); host.holdOpen(true); });
  input.addEventListener("blur", () => { host.keyboard(false); host.holdOpen(false); });
  input.addEventListener("mousedown", (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") onEnter();
    else if (e.key === "Escape") input.blur();
  });
  return input;
}

/** A row's text: a click turns it into a field, Enter saves, Escape leaves it as it was. */
function editable(host: FieldHost, text: string, save: (next: string) => void): HTMLElement {
  const label = h("span", { class: "ag-text", text, title: "Click to edit" });
  label.addEventListener("click", (e) => {
    e.stopPropagation();
    const input = field(host, "", "ag-edit", () => {
      const next = input.value.trim();
      if (next && next !== text) save(next);
      else input.replaceWith(label);
    });
    input.value = text;
    input.addEventListener("blur", () => input.isConnected && input.replaceWith(label));
    label.replaceWith(input);
    window.setTimeout(() => { input.focus(); input.select(); }, 120);
  });
  return label;
}

const smallBtn = (name: "x" | "check", cls: string, title: string, onClick: () => void) =>
  h("button", { class: `ag-btn ${cls}`, title, onclick: (e: Event) => { e.stopPropagation(); onClick(); } }, icon(name, 11, 2.6));

function dueLabel(due: string): string {
  if (!due) return "";
  const today = dayKey(new Date());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000));
  if (due === today) return "Today";
  if (due === tomorrow) return "Tomorrow";
  const d = new Date(`${due}T00:00:00`);
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function whenLabel(at: number): string {
  const d = new Date(at);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const key = dayKey(d);
  if (key === dayKey(new Date())) return time;
  if (key === dayKey(new Date(Date.now() + 86_400_000))) return `Tomorrow ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

function todoRow(host: FieldHost, t: Todo): HTMLElement {
  const overdue = t.due !== "" && t.due < dayKey(new Date());
  return div("ag-row",
    smallBtn("check", "tick", "Done", () => void Agenda.request({ op: "todo_done", id: t.id })),
    editable(host, t.text, (text) => void Agenda.request({ op: "todo_edit", id: t.id, text })),
    t.due ? h("span", { class: `ag-chip ${overdue ? "late" : ""}`, text: dueLabel(t.due) }) : null,
    smallBtn("x", "", "Remove", () => void Agenda.request({ op: "todo_remove", id: t.id })));
}

function reminderRow(host: FieldHost, r: Reminder): HTMLElement {
  return div("ag-row",
    h("span", { class: "ag-chip when", text: whenLabel(r.at) }),
    editable(host, r.text, (text) => void Agenda.request({ op: "reminder_edit", id: r.id, text })),
    smallBtn("x", "", "Remove", () => void Agenda.request({ op: "reminder_remove", id: r.id })));
}

// ── The panel on the Controls page ────────────────────────────────────────────

export interface AgendaPanel {
  el: HTMLElement;
  sync(): void;
}

export function buildAgendaPanel(host: FieldHost): AgendaPanel {
  let tab: "todo" | "reminder" = "todo";
  let drawn = "";
  const tabs = div("ag-tabs");
  const list = div("ag-list lv-scroll");
  const what = field(host, "", "grow", () => add());
  const when = field(host, "when: in 20 min · tomorrow 9am", "ag-when", () => add());
  const form = div("ag-form", what, when);

  function add() {
    const text = what.value.trim();
    if (!text) return;
    const done = (ok: boolean) => {
      if (!ok) return refused(what);
      what.value = "";
      when.value = "";
      what.title = "";
    };
    if (tab === "todo") void Agenda.request({ op: "todo_add", text }).then(done);
    else void Agenda.request({ op: "reminder_add", text, when: when.value.trim() || "in 1 hour" }).then(done);
  }

  const pick = (next: "todo" | "reminder") => {
    tab = next;
    drawn = "";
    State.notify();
  };

  return {
    el: div("ag", tabs, form, list),
    sync() {
      Agenda.refresh();
      const key = `${tab}|${Agenda.version}`;
      if (key === drawn) return;
      drawn = key;
      tabs.replaceChildren(
        h("button", { class: `ag-tab ${tab === "todo" ? "on" : ""}`, onclick: (e: Event) => { e.stopPropagation(); pick("todo"); } }, `To-do${Agenda.todos.length ? ` ${Agenda.todos.length}` : ""}`),
        h("button", { class: `ag-tab ${tab === "reminder" ? "on" : ""}`, onclick: (e: Event) => { e.stopPropagation(); pick("reminder"); } }, `Reminders${Agenda.reminders.length ? ` ${Agenda.reminders.length}` : ""}`),
      );
      what.placeholder = tab === "todo" ? "Add a to-do… (“by friday” dates it)" : "Remind me to…";
      when.style.display = tab === "todo" ? "none" : "";
      const rows = tab === "todo" ? Agenda.todos.map((t) => todoRow(host, t)) : Agenda.reminders.map((r) => reminderRow(host, r));
      // Why nothing can be kept (CLOVE not running, or too old) takes the empty list's place, in its grey.
      const empty = Agenda.error || (tab === "todo" ? "Nothing to do. Add one here, or tell CLOVE." : "No reminders. Add one here, or say “remind me…”.");
      list.replaceChildren(...(rows.length ? rows : [h("span", { class: "ag-empty", text: empty })]));
    },
  };
}

// ── One day, beside the calendar ──────────────────────────────────────────────

export interface DayPanel {
  el: HTMLElement;
  /** Shows `day`, or nothing when null. */
  sync(day: Date | null): void;
}

export function buildDayPanel(host: FieldHost, close: () => void): DayPanel {
  const title = div("ag-day-title");
  const list = div("ag-list lv-scroll");
  let current: Date | null = null;
  let drawn = "";
  const what = field(host, "Remind me that day to…", "grow", () => add());
  const at = field(host, "09:00", "ag-time", () => add());
  const link = field(host, "Connect a calendar: paste its https iCal address", "grow", () => {
    if (link.value.trim()) void Agenda.request({ op: "calendar", url: link.value.trim() }).then((ok) => (ok ? (link.value = "") : refused(link)));
  });
  // Shown when asked for: a link while no calendar is connected.
  const connect = div("ag-form ag-connect", link);
  connect.style.display = "none";
  const connectLink = h("button", { class: "ag-link", onclick: (e: Event) => {
    e.stopPropagation();
    connect.style.display = "";
    connectLink.style.display = "none";
    window.setTimeout(() => link.focus(), 120);
  } }, "Connect your calendar");

  function add() {
    const text = what.value.trim();
    if (!text || !current) return;
    const when = `${dayKey(current)} ${/^\d{1,2}:\d{2}$/.test(at.value.trim()) ? at.value.trim() : "09:00"}`;
    void Agenda.request({ op: "reminder_add", text, when }).then((ok) => {
      if (ok) what.value = "";
      else refused(what);
    });
  }

  const el = div("ag ag-day",
    div("ag-day-head", title, h("button", { class: "ag-btn", title: "Back to the world clocks", onclick: (e: Event) => { e.stopPropagation(); close(); } }, icon("x", 11, 2.6))),
    list, div("ag-form", what, at), connect, div("ag-foot", connectLink));

  return {
    el,
    sync(day) {
      current = day;
      el.style.display = day ? "" : "none";
      if (!day) return;
      Agenda.refresh(day);
      const key = `${dayKey(day)}|${Agenda.version}`;
      if (key === drawn) return;
      drawn = key;
      title.textContent = day.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
      const { events, reminders, todos } = Agenda.on(day);
      const rows: HTMLElement[] = [
        ...events.map((e) => div("ag-row event",
          h("span", { class: "ag-chip cal", text: e.time ? `${e.time}${e.end && e.end !== e.time ? `–${e.end}` : ""}` : "All day" }),
          h("span", { class: "ag-text plain", text: e.where ? `${e.title} · ${e.where}` : e.title }))),
        ...reminders.map((r) => reminderRow(host, r)),
        ...todos.map((t) => todoRow(host, t)),
      ];
      const empty = Agenda.error || (Agenda.calendar ? "Nothing on this day." : "Nothing on this day yet.");
      list.replaceChildren(...(rows.length ? rows : [h("span", { class: "ag-empty", text: empty })]));
      if (Agenda.calendar) connect.style.display = "none";
      connectLink.style.display = Agenda.calendar || connect.style.display !== "none" ? "none" : "";
    },
  };
}

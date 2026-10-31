// CLOVE fork: LocalSend in Clove Notch (core/localsend.ts, Rust localsend.rs).
//
//   - receive: "Pixel wants to send you 3 files" → Decline / Accept → a progress bar → "Saved to Downloads" (Open)
//              or, for a message, the words with Copy.
//   - the strip of devices nearby, used after a drop ("Send to Pixel") with the transfer's progress in place.

import { LocalSend, bytes, type LsDevice, type LsProgress } from "../core/localsend";
import { State } from "../core/state";
import { N_, t, tl } from "../i18n/i18n";
import { clear, h, svg } from "./dom";
import { ICONS } from "./icons";
import type { ViewActions, ViewHost } from "./views";

export function deviceIcon(type: string): string {
  return type === "mobile" ? ICONS.phone : type === "web" ? ICONS.globe : ICONS.laptop;
}

function pct(p: LsProgress): number {
  return p.totalBytes > 0 ? Math.min(100, Math.round((p.doneBytes / p.totalBytes) * 100)) : 0;
}

/** A transfer's line: what is happening, and a bar while bytes move. */
export function progressLine(p: LsProgress): HTMLElement {
  const outgoing = p.direction === "out";
  const words: Record<string, string> = {
    waiting: t("Waiting for {0} to accept…", { 0: p.device }),
    running: outgoing ? t("Sending to {0} · {1}%", { 0: p.device, 1: pct(p) }) : t("Receiving from {0} · {1}%", { 0: p.device, 1: pct(p) }),
    done: outgoing ? t("Sent to {0}", { 0: p.device }) : t("Saved to Downloads"),
    declined: outgoing ? t("{0} declined", { 0: p.device }) : t("Declined"),
    cancelled: t("{0} cancelled", { 0: p.device }),
    failed: p.error ?? t("Something went wrong"),
  };
  const bar = h("div", { class: "ls-bar" }, h("i"));
  (bar.firstChild as HTMLElement).style.transform = `scaleX(${p.state === "done" ? 1 : pct(p) / 100})`;
  const line = h("div", { class: `ls-progress ls-${p.state}` },
    h("div", { class: "ls-progress-text" },
      p.state === "done" ? svg(ICONS.check, 11, { stroke: 2.4 }) : p.state === "failed" || p.state === "declined" ? svg(ICONS.xmark, 10) : h("span", { class: "ls-spinner" }),
      h("span", { text: words[p.state] ?? p.state })),
    ...(p.state === "running" || p.state === "waiting" || p.state === "done" ? [bar] : []));
  return line;
}

/** The devices nearby as buttons; `onPick` sends to one. Empty: says how to make one appear. */
export function deviceStrip(onPick: (d: LsDevice) => void): HTMLElement {
  const strip = h("div", { class: "ls-strip" });
  if (!LocalSend.devices.length) {
    strip.append(h("span", { class: "ls-none", text: t("Open LocalSend on your phone to send it there.") }));
    return strip;
  }
  for (const d of LocalSend.devices.slice(0, 4)) {
    strip.append(h("button", {
      class: "ls-device", title: d.deviceModel ? `${d.alias} · ${d.deviceModel}` : d.alias,
      onclick: (e: Event) => { e.stopPropagation(); onPick(d); },
    }, svg(deviceIcon(d.deviceType), 13, { stroke: 1.8 }), h("span", { text: d.alias })));
  }
  return strip;
}

export function buildReceive(actions: ViewActions): ViewHost {
  const icon = h("div", { class: "ls-avatar" });
  const title = h("div", { class: "title ls-title" });
  const sub = h("div", { class: "sub ls-sub" });
  const body = h("div", { class: "ls-body" });
  const row = h("div", { class: "actions" });
  const el = h("div", { class: "view" },
    h("div", { class: "card ls-card" },
      h("div", { class: "ls-wrap" }, icon, h("div", { class: "ls-main" }, title, sub, body, row))));
  let key = "";
  let leaveTimer: number | null = null;

  function leaveSoon(ms: number) {
    if (leaveTimer != null) window.clearTimeout(leaveTimer);
    leaveTimer = window.setTimeout(() => {
      leaveTimer = null;
      if (State.view === "receive" && !LocalSend.request) {
        LocalSend.clear();
        actions.setView(State.defaultView());
      }
    }, ms);
  }

  return {
    el,
    sync() {
      if (State.view !== "receive") return;
      const r = LocalSend.request;
      const p = LocalSend.progress?.direction === "in" ? LocalSend.progress : null;
      const m = LocalSend.message;
      const k = JSON.stringify([r?.id, p?.state, p ? pct(p) : 0, m?.text, document.documentElement.lang]);
      if (k === key) return;
      key = k;
      clear(icon);
      clear(body);
      clear(row);
      if (r) {
        icon.append(svg(deviceIcon(r.deviceType), 20, { stroke: 1.6 }));
        if (r.text != null) {
          title.textContent = t("{0} sent you a message", { 0: r.alias });
          sub.textContent = "";
          body.append(h("div", { class: "ls-text", text: r.text.slice(0, 400) }));
        } else {
          title.textContent = r.files.length === 1
            ? t("{0} wants to send you a file", { 0: r.alias })
            : t("{0} wants to send you {1} files", { 0: r.alias, 1: r.files.length });
          const names = r.files.slice(0, 2).map((f) => f.name).join(", ");
          const more = r.files.length > 2 ? ` ${t("+{0} more", { 0: r.files.length - 2 })}` : "";
          sub.textContent = `${names}${more} · ${bytes(r.total)}`;
        }
        row.append(
          h("button", { class: "btn secondary", text: tl("Decline"), onclick: () => void LocalSend.answer(false) }),
          h("button", { class: "btn primary", text: r.text != null ? tl("Show") : tl("Accept"), onclick: () => void LocalSend.answer(true) }),
        );
        return;
      }
      if (m) {
        icon.append(svg(ICONS.bubble, 18));
        title.textContent = t("From {0}", { 0: m.from });
        sub.textContent = "";
        body.append(h("div", { class: "ls-text", text: m.text.slice(0, 400) }));
        row.append(
          h("button", { class: "btn primary", text: tl("Copy"), onclick: () => { void navigator.clipboard?.writeText(m.text); LocalSend.clear(); actions.setView(State.defaultView()); } }),
          h("button", { class: "btn secondary", text: tl("Close"), onclick: () => { LocalSend.clear(); actions.setView(State.defaultView()); } }),
        );
        return;
      }
      if (p) {
        icon.append(svg(ICONS.download, 18, { stroke: 1.8 }));
        title.textContent = p.state === "done"
          ? (p.saved.length === 1 ? t("Got 1 file from {0}", { 0: p.device }) : t("Got {0} files from {1}", { 0: p.saved.length, 1: p.device }))
          : t("From {0}", { 0: p.device });
        sub.textContent = p.saved.length === 1 ? (p.saved[0].split("/").pop() ?? "") : "";
        body.append(progressLine(p));
        if (p.state === "done") {
          if (p.saved.length === 1) row.append(h("button", { class: "btn primary", text: tl("Open"), onclick: () => LocalSend.open(p.saved[0]) }));
          if (p.folder) row.append(h("button", { class: "btn secondary", text: tl("Show in folder"), onclick: () => LocalSend.open(p.folder!) }));
          leaveSoon(12_000);
        } else if (p.state !== "running") {
          leaveSoon(4000);
        }
      }
    },
  };
}

// Strings shown through variables (the i18n checker reads these).
void [N_("Decline"), N_("Accept"), N_("Show"), N_("Copy"), N_("Close"), N_("Open"), N_("Show in folder")];

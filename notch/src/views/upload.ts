// Drop zone, upload progress and the "what do you want to do with it" card —
// ports of UploadView / UploadingView / ChooseView from IslandViewContent.swift.
//
// Sending a file by email is not in the Windows v1, so `choose` offers the one
// action the spec asks for: ask a question about it.

import { h, clear, svg } from "./dom";
import { ICONS } from "./icons";
import { State } from "../core/state";
import type { ViewActions, ViewHost } from "./views";
import { t, tl } from "../i18n/i18n";
import { LocalSend } from "../core/localsend";
import { deviceStrip, progressLine } from "./localsend";

/** Dashed rounded rect drawn as SVG so the dashes can march like on macOS. */
function dashedFrame(): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const el = document.createElementNS(ns, "svg");
  el.setAttribute("class", "drop-frame");
  el.setAttribute("preserveAspectRatio", "none");
  const rect = document.createElementNS(ns, "rect");
  rect.setAttribute("x", "0.75");
  rect.setAttribute("y", "0.75");
  rect.setAttribute("width", "calc(100% - 1.5px)");
  rect.setAttribute("height", "calc(100% - 1.5px)");
  rect.setAttribute("rx", "20");
  rect.setAttribute("fill", "none");
  rect.setAttribute("stroke-width", "1.5");
  rect.setAttribute("stroke-dasharray", "6 5");
  el.append(rect);
  return el;
}

export function buildUpload(actions: ViewActions): ViewHost {
  const frame = dashedFrame();
  const title = h("div", { class: "drop-title", text: tl("Drop files here, or double-click to choose") });
  // CLOVE fork: what he can do from here, at a glance: send (pick files), receive (LocalSend), talk (the chat).
  const act = (cls: string, label: string, icon: string, run: () => void) => h("button", {
    class: `drop-act ${cls}`,
    onclick: (e: Event) => { e.stopPropagation(); run(); },
    ondblclick: (e: Event) => e.stopPropagation(),
  }, svg(icon, 15, { stroke: 1.8 }), h("span", { text: label }));
  const tags = h("div", { class: "drop-acts" },
    act("send", t("Send"), ICONS.send, () => actions.pickFiles()),
    act("receive", t("Receive"), ICONS.download, () => actions.setView("receive")),
    act("talk", t("Talk"), ICONS.bubble, () => actions.setView("prompt")),
  );
  // CLOVE fork: who it can go to over LocalSend, and how Clove Notch shows up there.
  const nearby = h("div", { class: "drop-nearby" });
  const card = h(
    "div",
    { class: "card drop-card" },
    frame,
    h("div", { class: "drop-body" }, title, tags, nearby),
  );
  const el = h("div", { class: "view" }, card);
  // A double-click anywhere on the drop page opens the file chooser.
  card.addEventListener("dblclick", (e) => {
    e.stopPropagation();
    actions.pickFiles();
  });
  let nearbyKey = "";

  return {
    el,
    sync() {
      card.classList.toggle("over", State.fileDragOver);
      card.classList.toggle("dragging", State.fileDragOver);
      const k = LocalSend.devices.map((d) => d.alias).join("|") + (LocalSend.me?.alias ?? "");
      if (k === nearbyKey) return;
      nearbyKey = k;
      clear(nearby);
      const names = LocalSend.devices.slice(0, 3).map((d) => d.alias);
      nearby.append(svg(ICONS.globe, 10, { stroke: 1.8 }), h("span", {
        text: names.length
          ? t("Send to {0} over LocalSend, or ask CLOVE about it", { 0: names.join(", ") })
          : t("Visible on LocalSend as {0}", { 0: LocalSend.me?.alias ?? "CLOVE" }),
      }));
    },
  };
}

export function buildUploading(): ViewHost {
  const label = h("span", { class: "up-name" });
  const percent = h("span", { class: "up-pct" });
  const fill = h("div", { class: "up-fill" });
  const glow = h("div", { class: "up-glow" });
  const card = h(
    "div",
    { class: "card up-card" },
    h("div", { class: "up-row" }, label, percent),
    h("div", { class: "up-track" }, fill, glow),
  );
  const el = h("div", { class: "view" }, card);

  return {
    el,
    sync() {
      const done = State.uploadProgress >= 0.999;
      const pct = Math.round(State.uploadProgress * 100);
      label.textContent = done
        ? `✓  ${State.droppedFile?.name ?? t("File")}`
        : t("Uploading {name}", { name: State.droppedFile?.name ?? t("file") });
      label.classList.toggle("done", done);
      percent.textContent = done ? "" : `${pct} %`;
      const w = State.uploadProgress * 526;
      fill.style.width = `${w}px`;
      glow.style.transform = `translateX(${Math.max(0, w - 14)}px)`;
      glow.style.opacity = State.uploadProgress > 0.01 ? "1" : "0";
      card.classList.toggle("done", done);
    },
  };
}

export function buildChoose(actions: ViewActions): ViewHost {
  const title = h("div", { class: "title" });
  const sub = h("div", { class: "sub", text: tl("What do you want to do with it?") });
  const row = h(
    "div",
    { class: "actions" },
    h("button", {
      class: "btn primary",
      text: tl("Ask a question"),
      onclick: () => actions.setView("prompt"),
    }),
    h("button", {
      class: "btn secondary",
      text: tl("Cancel"),
      onclick: () => actions.cancelDrop(),
    }),
  );
  // CLOVE fork: LocalSend — "Send to …" for each device nearby, and the transfer's progress in its place.
  const send = h("div", { class: "ls-send" });
  const el = h(
    "div",
    { class: "view" },
    h(
      "div",
      { class: "card" },
      h("div", { class: "stack", style: "padding:0 18px 0 98px" }, title, sub, row, send),
    ),
  );
  let sendKey = "";

  return {
    el,
    sync() {
      clear(title);
      const n = LocalSend.dropped.length;
      if (n > 1) {
        title.append(h("b", { text: t("{0} files", { 0: n }) }), document.createTextNode(t(" are ready.")));
      } else {
        title.append(
          h("b", { text: State.droppedFile?.name ?? t("file") }),
          document.createTextNode(t(" is ready.")),
        );
      }
      const p = LocalSend.progress?.direction === "out" ? LocalSend.progress : null;
      const k = JSON.stringify([p?.state, p ? Math.round((p.doneBytes / Math.max(1, p.totalBytes)) * 100) : -1,
        LocalSend.devices.map((d) => d.id), document.documentElement.lang]);
      if (k === sendKey) return;
      sendKey = k;
      clear(send);
      if (p) send.append(progressLine(p));
      else send.append(deviceStrip((d) => void LocalSend.send(d.id, LocalSend.dropped)));
    },
  };
}

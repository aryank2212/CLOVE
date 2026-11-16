// CLOVE fork: LocalSend on the page side (Rust: localsend.rs). The devices nearby, a transfer someone wants to
// send him (Accept / Decline), and the progress of a transfer either way.

import { invoke } from "@tauri-apps/api/core";
import { IS_TAURI } from "./bridge";
import { State } from "./state";

export interface LsDevice {
  id: string;
  alias: string;
  deviceType: string;
  deviceModel: string;
  ip: string;
}

export interface LsRequest {
  id: number;
  alias: string;
  deviceType: string;
  files: { name: string; size: number }[];
  total: number;
  text: string | null;
}

export interface LsProgress {
  direction: "in" | "out";
  device: string;
  doneBytes: number;
  totalBytes: number;
  /** waiting (for them to accept) | running | done | declined | cancelled | failed */
  state: string;
  error: string | null;
  saved: string[];
  folder: string | null;
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!IS_TAURI) return null;
  try {
    return await invoke<T>(cmd, args);
  } catch (e) {
    return Promise.reject(e);
  }
}

class LocalSendState {
  devices: LsDevice[] = [];
  me: { alias: string; port: number } | null = null;
  request: LsRequest | null = null;
  /** The text of an accepted message (LocalSend's "send text"), to show and copy. */
  message: { from: string; text: string } | null = null;
  progress: LsProgress | null = null;
  /** Files dropped on Clove Notch, for "Send to …". */
  dropped: string[] = [];
  /** Called when a transfer is offered (the island opens on it). */
  onRequest: (() => void) | null = null;

  async refresh() {
    const list = await call<LsDevice[]>("localsend_devices").catch(() => null);
    if (list) this.devices = list;
    if (!this.me) {
      const me = await call<[string, number] | null>("localsend_me").catch(() => null);
      if (me) this.me = { alias: me[0], port: me[1] };
    }
    State.notify();
  }

  setDevices(list: LsDevice[]) {
    this.devices = list;
    State.notify();
  }

  offered(r: LsRequest) {
    this.request = r;
    this.progress = null;
    this.onRequest?.();
    State.notify();
  }

  async answer(accept: boolean) {
    const r = this.request;
    if (!r) return;
    this.request = null;
    if (accept && r.text != null) this.message = { from: r.alias, text: r.text };
    State.notify();
    await call<boolean>("localsend_answer", { id: r.id, accept }).catch(() => false);
  }

  progressed(p: LsProgress) {
    this.progress = p;
    State.notify();
  }

  async send(deviceId: string, paths: string[]) {
    const dev = this.devices.find((d) => d.id === deviceId);
    this.progress = {
      direction: "out", device: dev?.alias ?? "", doneBytes: 0, totalBytes: 0, state: "waiting",
      error: null, saved: [], folder: null,
    };
    State.notify();
    await call<void>("localsend_send", { device: deviceId, paths }).catch((e) => {
      this.progress = { ...this.progress!, state: "failed", error: String(e) };
      State.notify();
    });
  }

  /** The desktop's file chooser; the files picked, or [] if he closed it. */
  async pick(title: string): Promise<string[]> {
    return (await call<string[]>("pick_files", { title }).catch(() => null)) ?? [];
  }

  open(path: string) {
    void call<boolean>("localsend_open", { path }).catch(() => false);
  }

  clear() {
    this.progress = null;
    this.message = null;
    State.notify();
  }
}

export const LocalSend = new LocalSendState();

/** 12.4 MB, 830 KB, 2 B. */
export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

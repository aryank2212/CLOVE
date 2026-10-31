// Runs inside WhatsApp Web and Google Meet pages (page world, before the page's own code), on macOS only.
// macOS can't move one app's audio to another device from outside, so for a call CLOVE handles, this points the
// call page's microphone at "BlackHole 2ch" (Clove's voice) and its speakers at "BlackHole 16ch" (what Clove hears).
// Nothing changes until CLOVE asks (background.js "call_audio_route"); "release" puts the real devices back.
(() => {
  const mac = /Mac/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");
  if (!mac || window.__cloveRoute) return;
  const md = navigator.mediaDevices;
  const R = window.__cloveRoute = { mic: "", speaker: "", owner: false, on: false, pcs: new Set(), ctxs: new Set(), els: new Set(), mine: new Set() };
  const origGUM = md && md.getUserMedia ? md.getUserMedia.bind(md) : null;
  const CLEAN = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

  async function deviceId(kind, label) {
    if (!label || !md) return null;
    const d = (await md.enumerateDevices()).find((x) => x.kind === kind && x.label && x.label.toLowerCase().includes(label.toLowerCase()));
    return d ? d.deviceId : null;
  }
  const wantMic = () => (R.on && !R.owner ? deviceId("audioinput", R.mic) : Promise.resolve(null));

  // a microphone the page asks for while CLOVE has the call is Clove's voice
  if (origGUM) {
    md.getUserMedia = async (c) => {
      if (c && c.audio) {
        const id = await wantMic().catch(() => null);
        if (id) c = { ...c, audio: { ...(typeof c.audio === "object" ? c.audio : {}), deviceId: { exact: id }, ...CLEAN } };
      }
      return origGUM(c);
    };
  }
  // remember the call's connections, audio graphs and players, so they can be re-pointed later
  const track = (Orig, set) => (Orig ? new Proxy(Orig, { construct(t, a, nt) { const o = Reflect.construct(t, a, nt); set.add(o); return o; } }) : Orig);
  if (window.RTCPeerConnection) window.RTCPeerConnection = track(window.RTCPeerConnection, R.pcs);
  if (window.AudioContext) window.AudioContext = track(window.AudioContext, R.ctxs);
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...a) { R.els.add(this); if (R.on && R.sinkId != null && this.setSinkId && this.sinkId !== R.sinkId) this.setSinkId(R.sinkId).catch(() => {}); return play.apply(this, a); };

  R.apply = async (cfg) => {
    const release = !!cfg.release;
    R.on = !release; R.mic = cfg.mic || R.mic; R.speaker = cfg.speaker || R.speaker; R.owner = !!cfg.owner;
    const out = { mic: 0, speaker: 0, err: [] };
    // speakers
    let sink = "";
    if (!release) {
      sink = await deviceId("audiooutput", R.speaker);
      if (!sink) { out.err.push(`no "${R.speaker}" output visible to the page`); sink = null; }
    }
    R.sinkId = sink;
    if (sink !== null) {
      const players = new Set([...document.querySelectorAll("audio,video"), ...R.els]);
      for (const el of players) {
        if (!el.setSinkId) continue;
        if (el.sinkId !== sink) { try { await el.setSinkId(sink); } catch (e) { out.err.push("player: " + e.name); continue; } }
        if (sink) out.speaker++;
      }
      for (const ctx of R.ctxs) {
        if (!ctx.setSinkId || ctx.state === "closed") continue;
        if (ctx.sinkId !== sink) { try { await ctx.setSinkId(sink); } catch (e) { out.err.push("audio graph: " + e.name); continue; } }
        if (sink) out.speaker++;
      }
    }
    // microphone: swap the track each connection sends; keep the page's own track to give back
    const id = await wantMic().catch(() => null);
    if (!release && !R.owner && !id) out.err.push(`no "${R.mic}" input visible to the page`);
    for (const pc of R.pcs) {
      if (pc.connectionState === "closed" || pc.signalingState === "closed") { R.pcs.delete(pc); continue; }
      for (const s of pc.getSenders()) {
        const cur = s.track;
        if (!cur || cur.kind !== "audio") continue;
        if (!s.__cloveOrig && !R.mine.has(cur)) s.__cloveOrig = cur;
        try {
          if (id) {
            if (cur.getSettings().deviceId !== id) {
              const [t] = (await origGUM({ audio: { deviceId: { exact: id }, ...CLEAN } })).getAudioTracks();
              t.enabled = true;
              R.mine.add(t);
              await s.replaceTrack(t);
              if (R.mine.has(cur)) { cur.stop(); R.mine.delete(cur); }
            }
            out.mic++;
          } else if (s.__cloveOrig && cur !== s.__cloveOrig) {          // he talks himself, or the call is over
            await s.replaceTrack(s.__cloveOrig);
            if (R.mine.has(cur)) { cur.stop(); R.mine.delete(cur); }
          }
        } catch (e) { out.err.push("mic: " + e.name); }
      }
    }
    if (release) { R.mic = ""; R.speaker = ""; }
    return `mic ${out.mic}; speaker ${out.speaker}` + (out.err.length ? `; err: ${[...new Set(out.err)].join(", ")}` : "");
  };
})();

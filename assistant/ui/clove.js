// The CLOVE window. Everything shown comes from the backend over the local websocket; nothing is simulated.
// It runs on its own (a Chrome app window) or inside Clove Notch's window (?embed=1), where Clove Notch's
// sidebar picks the page and this one leaves its own out.
'use strict';
const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const token = params.get('t');
const EMBED = params.get('embed') === '1' && window.parent !== window;
const VIEWS = ['chat', 'activity', 'systems', 'prefs'];
const S = {
  conn: false, state: 'offline', mic: 0, out: 0, tasks: 0, muted: false,
  engine: null, info: null, prefs: {}, services: [], svcChecked: 0, tel: null, ws: null,
  plan: null, acts: new Map(), cur: {}, last: { you: null, clove: null }, events: [], unread: 0,
  overview: null, route: null, view: 'chat', lastSend: { text: '', t: 0 }, since: 0, shown: true,
};
let ws, failures = 0;

// ---------- small helpers ----------
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hhmm = ts => new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
const ago = ts => { if (!ts) return ''; const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 5 ? 'just now' : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`; };
const gb = b => b >= 2 ** 40 ? (b / 2 ** 40).toFixed(1) + ' TB' : (b / 2 ** 30).toFixed(b >= 100 * 2 ** 30 ? 0 : 1) + ' GB';
const rate = b => b == null ? '—' : b > 2 ** 20 ? (b / 2 ** 20).toFixed(1) + ' MB/s' : (b / 1024).toFixed(0) + ' KB/s';
// Only conveniences live here (the port, and so this storage, changes every run); real settings are the backend's.
const store = { get(k, d) { try { const v = sessionStorage.getItem('clove.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
                set(k, v) { try { sessionStorage.setItem('clove.' + k, JSON.stringify(v)); } catch {} } };
function send(obj) { if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; } return false; }
// Redraw only what changed: rebuilding a button under the pointer swallows the click (mousedown lands on the old
// one, mouseup on the new), so every area that holds buttons is keyed on what it shows.
const drawn = new WeakMap();
function changed(el, key) { if (drawn.get(el) === key) return false; drawn.set(el, key); return true; }
function setHTML(el, html) { if (changed(el, html)) el.innerHTML = html; }
function h(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function toast(text, level = 'info') {
  if (!text) return;
  const t = h('div', 'toast ' + level); t.textContent = text; $('toasts').appendChild(t);
  setTimeout(() => t.remove(), level === 'info' ? 4500 : 8000);
}
const reduced = () => document.body.classList.contains('reduce') || matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------- drawing: one loop for every canvas, stopped when nothing is on screen ----------
// The same look as Clove Notch's window (hub/hero.ts): a deep black, the page's colour breathing in a corner, and
// particles that drift and move away from the pointer.
const live = new Set();
let frame = null, lastFrame = 0;
const MIN_FRAME = EMBED ? 1000 / 30 : 0;          // inside Clove Notch (WebKitGTK) 30 fps is plenty
function visible(el) { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight; }
const animating = () => live.size > 0 && S.shown && document.visibilityState === 'visible' && !reduced();
function loop(now) {
  frame = null;
  if (now - lastFrame >= MIN_FRAME) {
    const dt = Math.min(0.05, (now - (lastFrame || now)) / 1000); lastFrame = now;
    for (const a of live) if (visible(a.el)) a.draw(dt, now / 1000);
  }
  if (animating()) frame = requestAnimationFrame(loop);
}
function wake() {
  if (reduced()) { for (const a of live) if (visible(a.el)) a.draw(0, performance.now() / 1000); return; }   // one still frame
  if (frame === null && animating()) { lastFrame = 0; frame = requestAnimationFrame(loop); }
}
document.addEventListener('visibilitychange', wake);
addEventListener('resize', wake);
function fit(canvas) {
  const dpr = Math.min(2, devicePixelRatio || 1), w = canvas.clientWidth, hh = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hh * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(hh * dpr); }
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w, h: hh, ctx };
}
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a))})`;

function backdrop(canvas, color) {
  const c = rgb(color), host = canvas.parentElement;
  let parts = [], pointer = null, strength = 0;
  host.style.setProperty('--hero-line', rgba(c, 0.16));
  host.addEventListener('pointermove', e => { const r = canvas.getBoundingClientRect(); pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; });
  host.addEventListener('pointerleave', () => pointer = null);
  const seed = (w, hh) => {
    const n = Math.round(Math.min(90, Math.max(24, w * hh / 2600)));
    parts = Array.from({ length: n }, () => ({ x: Math.random() * w, y: Math.random() * hh, vx: (Math.random() - 0.5) * 6, vy: -2 - Math.random() * 6,
      r: 0.5 + Math.random() * 1.4, depth: 0.35 + Math.random() * 0.65, phase: Math.random() * Math.PI * 2, white: Math.random() < 0.35 }));
  };
  live.add({ el: canvas, draw(dt, t) {
    const { w, h: hh, ctx } = fit(canvas); if (!w) return;
    if (!parts.length) seed(w, hh);
    strength += ((pointer ? 1 : 0) - strength) * Math.min(1, dt * 4);
    ctx.clearRect(0, 0, w, hh);
    ctx.fillStyle = '#020203'; ctx.fillRect(0, 0, w, hh);
    const lin = ctx.createLinearGradient(w, 0, w * 0.35, hh);
    lin.addColorStop(0, rgba(c, 0.1)); lin.addColorStop(1, 'rgba(0,0,0,0)'); ctx.fillStyle = lin; ctx.fillRect(0, 0, w, hh);
    const breath = 0.85 + 0.15 * Math.sin(t * 0.9);
    const rad = ctx.createRadialGradient(w * 0.92, -hh * 0.15, 0, w * 0.92, -hh * 0.15, Math.max(w, hh) * 0.55 * breath);
    rad.addColorStop(0, rgba(c, 0.3 * breath)); rad.addColorStop(0.5, rgba(c, 0.08)); rad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = rad; ctx.fillRect(0, 0, w, hh);
    for (const p of parts) {
      p.x += p.vx * dt * p.depth; p.y += p.vy * dt * p.depth;
      let alpha = (0.22 + 0.5 * (0.5 + 0.5 * Math.sin(t * (1.2 + p.depth) + p.phase))) * p.depth, r = p.r;
      if (pointer && strength > 0.01) {
        const dx = p.x - pointer.x, dy = p.y - pointer.y, d = Math.hypot(dx, dy);
        if (d < 140 && d > 0.1) { const push = (1 - d / 140) * 90 * strength * dt; p.x += dx / d * push; p.y += dy / d * push; }
        if (d < 200) { const near = (1 - d / 200) * strength; alpha += near * 0.6; r *= 1 + near * 0.8; }
      }
      if (p.y < -4) p.y = hh + 4; if (p.y > hh + 4) p.y = -4; if (p.x < -4) p.x = w + 4; if (p.x > w + 4) p.x = -4;
      const tint = p.white ? [255, 255, 255] : c;
      if (r > 1.1) { ctx.fillStyle = rgba(tint, Math.min(1, alpha) * 0.12); ctx.beginPath(); ctx.arc(p.x, p.y, r * 2.6, 0, 7); ctx.fill(); }
      ctx.fillStyle = rgba(tint, Math.min(1, alpha)); ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.fill();
    }
  } });
}

// ---------- the CLOVE mark: four sepals around a bud in a state ring (drawCloveMark of Clove Notch) ----------
const SOFT = [231, 237, 245], ORANGE = rgb('#FB923C'), AMBER = rgb('#F7B32B'), GREY = rgb('#6B7079');
function drawMark(x, R, accent, tint, open = 1, yaw = 0, pitch = 0, ring = true) {
  const mix = (a, b) => Math.round(a + (b - a) * tint * 0.55);
  const petal = [mix(SOFT[0], accent[0]), mix(SOFT[1], accent[1]), mix(SOFT[2], accent[2])];
  if (ring) { x.beginPath(); x.arc(0, 0, R * 1.08, 0, Math.PI * 2); x.strokeStyle = rgba(accent, 0.25 + 0.6 * tint); x.lineWidth = Math.max(1, R * 0.07); x.stroke(); }
  const reach = R * (0.9 + 0.08 * open);
  x.fillStyle = rgba(petal, 1);
  for (let k = 0; k < 4; k++) {
    x.save(); x.rotate(k * Math.PI / 2); x.beginPath();
    x.moveTo(0, -reach); x.lineTo(R * 0.21, -R * 0.33); x.lineTo(0, -R * 0.16); x.lineTo(-R * 0.21, -R * 0.33);
    x.closePath(); x.fill(); x.restore();
  }
  x.beginPath(); x.arc(Math.sin(yaw) * R * 0.1, Math.sin(pitch) * R * 0.1, R * 0.17, 0, Math.PI * 2);
  x.fillStyle = 'rgb(8,10,15)'; x.fill(); x.lineWidth = Math.max(1, R * 0.065); x.strokeStyle = rgba(petal, 1); x.stroke();
}
function stillMark(canvas, R, tint = 0.35) {
  const { w, h: hh, ctx } = fit(canvas); if (!w) return;
  ctx.clearRect(0, 0, w, hh); ctx.save(); ctx.translate(w / 2, hh / 2); drawMark(ctx, R, ORANGE, tint); ctx.restore();
}

// The presence on the conversation band: it walks about while CLOVE waits, stops and faces you when it listens,
// thinks or speaks; its ring follows your voice and CLOVE's, spins while it works, and turns amber when a plan
// needs your yes.
const P = { x: null, target: null, dir: 1, hop: 0, hopV: 0, pause: 1.5, next: 4, blink: 0, nextBlink: 3, spin: 0, squash: 0, pointer: null };
function presence(canvas) {
  canvas.addEventListener('pointermove', e => { const r = canvas.getBoundingClientRect(); P.pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; });
  canvas.addEventListener('pointerleave', () => P.pointer = null);
  canvas.addEventListener('click', () => { if (!reduced()) P.hopV = 240; S.state === 'speaking' ? send({ type: 'stop' }) : send({ type: 'wake' }); });
  live.add({ el: canvas, draw(dt, t) {
    const { w, h: hh, ctx } = fit(canvas); if (!w) return;
    const compact = document.body.classList.contains('compact');
    const R = compact ? 15 : hh < 130 ? 19 : 23, pad = R + 18, lo = pad, hi = Math.max(pad, w - pad);
    const st = S.conn ? S.state : 'offline';
    const roams = ['idle', 'sleeping', 'focus'].includes(st) && !reduced() && !compact;
    if (P.x === null || P.x < lo || P.x > hi) { P.x = hi - (hi - lo) * 0.3; P.target = P.x; }
    if (roams) {
      if (Math.abs(P.target - P.x) < 1) { P.pause -= dt; if (P.pause <= 0) { P.target = lo + Math.random() * (hi - lo); P.pause = 2 + Math.random() * 4; } }
      else { const step = Math.sign(P.target - P.x) * Math.min(Math.abs(P.target - P.x), 26 * dt); P.x += step; P.dir = Math.sign(step) || P.dir;
             if (P.hop === 0 && P.hopV === 0) P.hopV = 60; }
      P.next -= dt; if (P.next <= 0) { P.next = 5 + Math.random() * 7; if (Math.random() < 0.5) P.hopV = 190; }
    } else P.target = P.x;
    if (P.hopV !== 0 || P.hop > 0) { P.hopV -= 900 * dt; P.hop = Math.max(0, P.hop + P.hopV * dt); if (P.hop === 0 && P.hopV < 0) { P.hopV = 0; P.squash = 1; } }
    P.squash = Math.max(0, P.squash - dt * 5);
    P.nextBlink -= dt; if (P.nextBlink <= 0) { P.blink = 1; P.nextBlink = 3 + Math.random() * 4; }
    P.blink = Math.max(0, P.blink - dt * 6);
    const lvl = st === 'speaking' ? S.out : ['listening', 'dictating'].includes(st) ? S.mic : 0;
    const accent = st === 'waiting' ? AMBER : st === 'offline' ? GREY : ORANGE;
    const tint = { offline: 0.1, sleeping: 0.3, idle: 0.4, focus: 0.25, waiting: 0.8 }[st] ?? 0.55 + Math.min(0.45, lvl * 1.2);
    const looking = P.pointer ? [(P.pointer.x - P.x) / 160, (P.pointer.y - hh / 2) / 120] : roams ? [P.dir * 0.5, 0.1 * Math.sin(t)] : [0, 0.15];
    const cy = hh - 14 - R * 1.1 - P.hop;
    ctx.clearRect(0, 0, w, hh);
    ctx.fillStyle = `rgba(0,0,0,${0.4 * (1 - Math.min(1, P.hop / 60))})`;
    ctx.beginPath(); ctx.ellipse(P.x, hh - 12, R * 0.75, R * 0.12, 0, 0, Math.PI * 2); ctx.fill();
    ctx.save(); ctx.translate(P.x, cy);
    const tilt = roams ? Math.sin(t * 3) * 0.05 * (Math.abs(P.target - P.x) > 1 ? 1 : 0) : 0;
    ctx.rotate(tilt); ctx.scale(1 + P.squash * 0.08, 1 - P.squash * 0.08);
    drawMark(ctx, R, accent, tint, 1 - P.blink, Math.max(-1, Math.min(1, looking[0])) * 0.8, Math.max(-1, Math.min(1, looking[1])) * 0.8);
    if (lvl > 0.01 || ['thinking', 'working'].includes(st)) {           // the ring's arc: a voice level, or work going on
      ctx.lineWidth = Math.max(1.5, R * 0.09); ctx.lineCap = 'round'; ctx.strokeStyle = rgba(accent, 0.95); ctx.beginPath();
      if (lvl > 0.01) ctx.arc(0, 0, R * 1.08, -Math.PI / 2, -Math.PI / 2 + Math.min(1, 0.06 + lvl * 2.2) * Math.PI * 2);
      else { P.spin += dt * 3.2; ctx.arc(0, 0, R * 1.08, P.spin, P.spin + 1.1); }
      ctx.stroke();
    }
    ctx.restore();
  } });
}

// ---------- assistant state (driven by the backend's tick) ----------
let notice = '';
const wakeWord = () => (S.info?.wake_names || ['clove']).map(n => n[0].toUpperCase() + n.slice(1)).join('" or "');
function headline() {
  if (!S.conn) return ['Not connected', 'bad'];
  return { sleeping: [`Hello${S.info?.user ? ', ' + S.info.user : ''}`, ''], idle: ['Ready', ''], listening: ['Listening', 'active'],
           thinking: ['Thinking', 'active'], speaking: ['Speaking', 'active'], working: ['Working', 'active'],
           waiting: ['Needs your approval', 'attn'], dictating: ['Dictating', 'active'], focus: ['Focus mode', ''],
           offline: ['No brain connected', 'bad'] }[S.state] || [S.state, ''];
}
function substate() {
  if (!S.conn) return failures > 4
    ? 'CLOVE is not answering at this address. If it restarted, open CLOVE again from the app grid or Clove Notch.'
    : 'The CLOVE backend is not reachable. Reconnecting…';
  if (notice) return notice;
  return { sleeping: `Say "${wakeWord()}" to talk, or type below.`, idle: 'Go ahead, I am listening.', listening: 'Listening to you.',
           thinking: 'Working out a reply.', speaking: 'Esc or a click on the mark stops it.', working: `${S.tasks} job${S.tasks === 1 ? '' : 's'} running.`,
           waiting: 'A plan is waiting: approve or reject it in Activity, by voice, or on Clove Notch.',
           dictating: 'Typing what you say into the focused window.', focus: 'Non-urgent updates are held until focus ends.',
           offline: 'Add GEMINI_API_KEY to .env or install Qwen, then restart CLOVE.' }[S.state] || '';
}
function statusLine() {
  if (!S.conn) return ['down', 'Not connected'];
  return { sleeping: ['ok', `Ready · say "${wakeWord()}"`], idle: ['ok', 'Ready'], listening: ['live', 'Listening'], thinking: ['live', 'Thinking'],
           speaking: ['live', 'Speaking'], working: ['live', `${S.tasks} job${S.tasks === 1 ? '' : 's'} running`],
           waiting: ['warn', 'Waiting for your approval'], dictating: ['live', 'Dictating'], focus: ['ok', 'Focus mode'],
           offline: ['down', 'No brain connected'] }[S.state] || ['off', S.state];
}
function renderState() {
  const [title, tone] = headline();
  $('state').textContent = title; $('substate').textContent = substate(); $('substate').title = substate();
  const hero = $('state').closest('.hero'); hero.classList.toggle('s-attn', tone === 'attn'); hero.classList.toggle('s-bad', tone === 'bad');
  const [dot, text] = statusLine(); $('status-dot').className = 'dot ' + dot; $('status-tx').textContent = text;
  $('stop').classList.toggle('hidden', S.state !== 'speaking');
  renderRoute(); renderCount(); wake();
}
function onLevels() {
  const micPct = S.muted ? 0 : Math.min(100, S.mic * 100);
  $('mic-bar').style.height = micPct + '%';
}

// ---------- conversation feed ----------
const feed = $('feed');
const nearBottom = () => feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
function stick(fn) { const b = nearBottom(); fn(); if (b) feed.scrollTop = feed.scrollHeight; }
function emptyState() {
  if (feed.querySelector('.line, .tool, .report')) { feed.querySelector('.empty')?.remove(); return; }
  if (feed.querySelector('.empty')) return;
  const w = S.ws?.ok && S.ws.git ? ` Workspace: ${esc(S.ws.name)} on ${esc(S.ws.branch)}.` : '';
  const e = h('div', 'empty', `<canvas aria-hidden="true"></canvas><div>Nothing said yet.${w} Say "${esc(wakeWord())}", or type below.</div>`);
  feed.appendChild(e); requestAnimationFrame(() => stillMark(e.querySelector('canvas'), 17, 0.2));
}
function caption(m) {
  const who = m.who === 'you' ? 'you' : 'clove';
  stick(() => {
    let el = S.cur[who];
    if (m.new || !el) {
      el = h('div', 'line ' + who, `<span class="ts">${hhmm(m.ts)}</span><div><div class="who">${who === 'you' ? 'You' : 'CLOVE'}</div><div class="said"></div></div>`);
      el.raw = ''; feed.appendChild(el); S.cur[who] = el;
      if (who === 'you') S.cur.clove = null;                // his new words start a new exchange
    }
    el.raw += m.text;
    const body = el.querySelector('.said');
    if (who === 'you') body.textContent = el.raw; else body.innerHTML = md(el.raw);
    S.last[who] = { text: el.raw, ts: m.ts };
  });
  emptyState(); renderMini();
}
function activity(m) {
  const prev = S.acts.get(m.id) || {};
  const a = { ...prev, ...m, ts: prev.ts || m.ts };
  S.acts.set(m.id, a);
  stick(() => {
    let el = document.getElementById('act-' + m.id);
    if (!el) {
      el = h('div', 'tool', `<span class="ts"></span><span class="dot"></span><span class="l"></span><span class="d"></span><span class="x"></span>`);
      el.id = 'act-' + m.id; feed.appendChild(el); S.cur = {};
    }
    const held = a.state === 'fail' && /^NEEDS APPROVAL/.test(a.detail || '');
    const st = a.state === 'running' ? 'running' : held ? 'held' : a.state;
    el.className = 'tool ' + st;
    el.querySelector('.ts').textContent = hhmm(a.ts);
    el.querySelector('.l').textContent = a.label;
    el.querySelector('.d').textContent = held ? 'held: waiting for your approval' : a.detail || (st === 'running' ? 'running…' : '');
    el.title = `${a.label}\n${a.detail || ''}`;
    const x = el.querySelector('.x'), cancellable = !!(a.job && st === 'running');
    if (cancellable !== !!x.firstChild) {
      x.textContent = '';
      if (cancellable) { const b = h('button', 'xbtn', 'Cancel'); b.title = 'Cancel this job'; b.onclick = () => send({ type: 'cancel_job', id: a.job }); x.appendChild(b); }
    }
  });
  emptyState(); renderJobs(); renderTimeline(); renderMini();
}
function report(m) {
  const key = 'rep-' + btoa(unescape(encodeURIComponent(m.title || ''))).slice(0, 16);
  let el = document.getElementById(key);
  stick(() => {
    if (!el) { el = h('details', 'report'); el.id = key; el.open = true; feed.appendChild(el); }
    el.innerHTML = `<summary><span class="tag">Report</span>${esc(m.title)}</summary><div class="said">${md(m.text || '')}</div>`;
  });
  emptyState();
}

// Minimal, safe Markdown: code fences (with copy), inline code, bold, links, lists, headings.
function md(src) {
  const out = []; const parts = String(src).split(/```(\w*)\n?([\s\S]*?)(?:```|$)/g);
  for (let i = 0; i < parts.length; i += 3) {
    out.push(block(parts[i]));
    if (i + 2 < parts.length) out.push(`<div class="code"><button class="copybtn">Copy</button><pre><code>${esc(parts[i + 2].replace(/\n$/, ''))}</code></pre></div>`);
  }
  return out.join('');
}
function inline(t) {
  return esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}
function block(t) {
  const html = []; let list = null;
  for (const line of t.split('\n')) {
    const li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
    if (li) { (list ??= []).push(`<li>${inline(li[1])}</li>`); continue; }
    if (list) { html.push(`<ul>${list.join('')}</ul>`); list = null; }
    const hd = line.match(/^#{1,4}\s+(.*)/);
    if (hd) html.push(`<h3>${inline(hd[1])}</h3>`); else if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  if (list) html.push(`<ul>${list.join('')}</ul>`);
  return html.join('');
}
document.addEventListener('click', async e => {
  const b = e.target.closest('.copybtn'); if (!b) return;
  try { await navigator.clipboard.writeText(b.nextElementSibling.textContent); b.textContent = 'Copied'; }
  catch { b.textContent = 'Select and press Ctrl+C'; }
  setTimeout(() => b.textContent = 'Copy', 1600);
});

// ---------- the plan card and jobs ----------
const ICON = { pending: '·', running: '›', done: '✓', failed: '✕', skipped: '–' };
function planCard(p, big) {
  const steps = p.steps || [];
  const fin = steps.length && steps.every(s => ['done', 'failed', 'skipped'].includes(s.status));
  const failed = steps.some(s => s.status === 'failed');
  const tag = p.approval === 'pending' ? ['pending', 'Needs approval'] : p.approval === 'declined' ? ['declined', 'Rejected']
    : fin ? (failed ? ['failed', steps.some(s => s.status === 'done') ? 'Partly done' : 'Failed'] : ['done', 'Completed'])
    : steps.some(s => s.status === 'running') ? ['running', 'Running'] : p.approval === 'approved' ? ['approved', 'Approved'] : ['', 'Plan'];
  const el = h('div', 'task' + (p.approval === 'pending' ? ' attn' : '') + (big ? ' card' : ''));
  el.innerHTML = `<div class="title"><span></span><span class="tag ${tag[0]}">${tag[1]}</span></div><ol class="steps"></ol>`;
  el.querySelector('.title span').textContent = p.title;
  const ol = el.querySelector('.steps');
  steps.forEach((s, i) => {
    const li = h('li', s.status, `<span class="i" aria-label="${esc(s.status)}">${ICON[s.status] || '·'}</span><span class="t"></span>`);
    li.querySelector('.t').textContent = `${i + 1}. ${s.text}`;
    if (s.note) { const n = h('span', 'note'); n.textContent = s.note; li.querySelector('.t').appendChild(n); }
    ol.appendChild(li);
  });
  if (p.approval === 'pending') {
    const acts = h('div', 'acts', '<button class="btn">Reject</button><button class="btn primary">Approve</button>');
    const [no, yes] = acts.querySelectorAll('button');
    const answer = v => { no.disabled = yes.disabled = true; if (!send({ type: 'approve', value: v })) { no.disabled = yes.disabled = false; toast('Not connected to CLOVE: nothing was approved or rejected.', 'warn'); } };
    no.onclick = () => answer(false); yes.onclick = () => answer(true);
    el.appendChild(acts);
  }
  return el;
}
const running = () => [...S.acts.values()].filter(a => a.job && a.state === 'running');
function jobRow(a, withTime) {
  const st = a.state === 'running' ? 'running' : a.state === 'ok' ? 'done' : 'failed';
  const r = h('div', 'job', `<span class="dot ${st === 'running' ? 'live' : st === 'done' ? 'ok' : 'down'}"></span><span class="l"></span>` +
    (st === 'running' ? '<button class="xbtn">Cancel</button>' : `<span class="tag ${st}">${st === 'done' ? 'Done' : 'Failed'}</span>`) + '<span class="d"></span>');
  r.querySelector('.l').textContent = a.label;
  r.querySelector('.d').textContent = (withTime ? `${hhmm(a.ts)} · ` : '') + (a.detail || (st === 'running' ? 'running' : ''));
  r.title = a.label + (a.detail ? '\n' + a.detail : '');
  r.querySelector('button')?.addEventListener('click', () => send({ type: 'cancel_job', id: a.job }));
  return r;
}
const jobsKey = () => JSON.stringify(running().map(a => [a.id, a.job, a.label, a.detail]));
function renderTask() {
  const body = $('task-body'), tp = $('tasks-plan');
  if (!changed(body, JSON.stringify(S.plan) + jobsKey() + S.conn)) { renderMini(); renderCount(); return; }
  body.textContent = '';
  const live_ = S.plan && !(S.plan.steps || []).every(s => ['done', 'failed', 'skipped'].includes(s.status)) && S.plan.approval !== 'declined';
  if (S.plan && (live_ || S.plan.approval === 'pending')) body.appendChild(planCard(S.plan));
  running().forEach(a => body.appendChild(jobRow(a)));
  if (!body.children.length) body.appendChild(h('div', 'quiet', S.plan ? `Last plan: ${esc(S.plan.title)}` : 'No active task.'));
  tp.textContent = '';
  tp.appendChild(S.plan ? planCard(S.plan, true) : h('div', 'card quiet', 'No plan yet. Requests with several steps show their checklist here, and anything risky waits for your yes.'));
  renderMini(); renderCount();
}
function renderJobs() {
  const list = [...S.acts.values()].filter(a => a.job).reverse();
  const box = $('tasks-jobs');
  if (!changed(box, JSON.stringify(list.map(a => [a.id, a.state, a.label, a.detail, a.ts])))) { renderTask(); return; }
  box.textContent = '';
  if (!list.length) box.appendChild(h('div', 'quiet', 'No background jobs this session.'));
  list.forEach(a => box.appendChild(jobRow(a, true)));
  renderTask();
}

// ---------- activity timeline ----------
function renderTimeline() {
  if (S.view !== 'activity') return;
  const rows = [...[...S.acts.values()].map(a => ({ ts: a.updated || a.ts, st: a.state === 'running' ? 'live' : a.state === 'ok' ? 'ok' : 'down',
                  a: a.label, b: a.detail || '' })),
                ...S.events.map(e => ({ ts: e.ts, st: e.level === 'warn' ? 'warn' : e.level === 'err' ? 'down' : 'off', a: e.text, b: '' }))]
    .sort((x, y) => y.ts - x.ts);
  const tl = $('timeline'); tl.textContent = '';
  if (!rows.length) { tl.appendChild(h('div', 'quiet', 'Nothing has happened yet this session.')); return; }
  for (const r of rows.slice(0, 300)) {
    const e = h('div', 'ev', `<span class="t">${hhmm(r.ts)}</span><span class="dot ${r.st}"></span><div class="x"><div class="a"></div><div class="b"></div></div>`);
    e.querySelector('.a').textContent = r.a; e.querySelector('.b').textContent = r.b || 'No further detail.';
    e.tabIndex = 0; e.onclick = () => e.classList.toggle('open');
    e.onkeydown = k => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); e.classList.toggle('open'); } };
    tl.appendChild(e);
  }
}
function renderCount() {
  const n = (S.plan?.approval === 'pending' ? 1 : 0) + S.unread;
  const c = $('act-n'); c.textContent = n > 9 ? '9+' : n; c.classList.toggle('hidden', !n);
  c.title = S.plan?.approval === 'pending' ? 'A plan needs your approval' : `${S.unread} new notice${S.unread === 1 ? '' : 's'}`;
  if (EMBED) parent.postMessage({ type: 'clove:attention', count: n, approval: S.plan?.approval === 'pending' }, '*');
}

// ---------- telemetry (this PC) ----------
function spark(vals, max) {
  if (!vals || vals.length < 2) return '<svg viewBox="0 0 100 20" preserveAspectRatio="none"><line x1="0" y1="19.5" x2="100" y2="19.5"/></svg>';
  const m = max || Math.max(...vals, 1), n = vals.length - 1;
  const pts = vals.map((v, i) => `${(i / n * 100).toFixed(1)},${(19 - v / m * 17).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 100 20" preserveAspectRatio="none"><line x1="0" y1="19.5" x2="100" y2="19.5"/><polyline points="${pts}"/></svg>`;
}
function metricsHTML(t) {
  const row = (n, v, hist, max, na) => `<div class="metric${na ? ' na' : ''}"><span class="n">${n}</span>${spark(hist, max)}<span class="v">${v}</span></div>`;
  const g = t.gpu;
  return row('CPU', t.cpu == null ? 'sampling' : t.cpu.toFixed(0) + '%', t.hist.cpu, 100) +
         row('Mem', `${(t.mem_used / 2 ** 30).toFixed(1)} / ${(t.mem_total / 2 ** 30).toFixed(1)} GB`, t.hist.mem, 100) +
         (g ? row('GPU', `${g.util.toFixed(0)}% · ${(g.mem_used / 1024).toFixed(1)} GB`, t.hist.gpu, 100) : row('GPU', 'unavailable', null, 0, true)) +
         row('Net', t.net_rx == null ? 'sampling' : `↓ ${rate(t.net_rx)}`, t.hist.net, 0);
}
function disksHTML(t) {
  return (t.disks || []).map(d => { const p = d.used / d.total * 100;
    return `<div class="disk" title="${esc(d.path)}"><span class="n">${esc(d.label)}</span><div class="meter"><i class="${p > 92 ? 'crit' : p > 80 ? 'hot' : ''}" style="width:${p.toFixed(0)}%"></i></div><span class="v" title="${gb(d.total - d.used)} free of ${gb(d.total)}">${p.toFixed(0)}% · ${gb(d.total - d.used)} free</span></div>`; }).join('');
}
function renderTelemetry() {
  const t = S.tel; if (!t) return;
  $('metrics').innerHTML = metricsHTML(t) + disksHTML(t);
  $('sys-metrics').innerHTML = metricsHTML(t);
  $('sys-disks').innerHTML = disksHTML(t);
  const up = t.uptime, d = Math.floor(up / 86400), hh = Math.floor(up % 86400 / 3600), mm = Math.floor(up % 3600 / 60);
  $('sys-extra').innerHTML = `<div>Load ${t.load.join(' ')} · ${t.cores} cores · up ${d ? d + 'd ' : ''}${hh}h ${mm}m</div>` +
    (t.gpu ? `<div>${esc(t.gpu.name)} · ${t.gpu.temp.toFixed(0)}°C</div>` : '<div>GPU telemetry unavailable (no nvidia-smi)</div>') +
    (t.net_rx != null ? `<div>Network ↓ ${rate(t.net_rx)} ↑ ${rate(t.net_tx)}</div>` : '');
  freshness();
}
function freshness() {
  const t = S.tel, now = Date.now() / 1000;
  for (const id of ['tel-fresh', 'sys-fresh']) {
    const e = $(id); if (!t) { e.textContent = S.conn ? 'waiting' : 'not connected'; continue; }
    const stale = !S.conn || now - t.ts > 8;
    e.textContent = stale ? `stale · ${ago(t.ts)}` : 'live'; e.classList.toggle('stale', stale);
  }
  for (const id of ['svc-fresh', 'svc-fresh2']) $(id).textContent = S.svcChecked ? 'checked ' + ago(S.svcChecked) : '';
}

// ---------- services and the sidebar's connections ----------
const WORD = { ok: 'OK', warn: 'Check', down: 'Down', off: 'Off', live: 'On' };
function svcHTML(list, full) {
  if (!list.length) return `<div class="quiet">${S.conn ? 'Checking…' : 'Not connected to CLOVE.'}</div>`;
  return list.map(s => `<div class="svc" title="${esc(s.detail)}${full ? '' : '\nchecked ' + ago(s.checked)}"><span class="dot ${s.state}"></span><span class="nm">${esc(s.name)}</span>` +
    `<span class="dt${full ? ' wrap' : ''}">${esc(s.detail)}${full ? ' · ' + ago(s.checked) : ''}</span></div>`).join('');
}
function renderServices() {
  setHTML($('services'), svcHTML(S.services)); setHTML($('svc-full'), svcHTML(S.services, true));
  renderConns(); freshness();
}
function renderConns() {
  const by = k => S.services.find(s => s.key === k);
  const e = S.engine, brain = e?.brains?.[e.active];
  const rows = [['prefs', 'Brain', !S.conn ? 'off' : e?.switching ? 'warn' : e?.active ? 'ok' : 'down',
                 !S.conn ? 'Off' : e?.switching ? '…' : brain?.label || 'None', brain ? `${brain.label} is answering` : 'No brain connected']];
  for (const [k, name] of [['gemini', 'Gemini API'], ['chrome', 'Chrome']]) {
    const s = by(k); rows.push(['systems', name, s?.state || 'off', s ? WORD[s.state] : '…', s?.detail || 'Checking…']);
  }
  for (const s of S.services.filter(s => s.key.startsWith('ssh-'))) rows.push(['systems', s.name.replace(' (SSH)', ''), s.state, WORD[s.state], s.detail]);
  rows.push(['prefs', 'Microphone', !S.conn ? 'off' : S.muted ? 'off' : 'ok', S.muted ? 'Muted' : 'On', S.route?.label || 'Microphone']);
  setHTML($('conns'), rows.map(([go, name, st, word, tip]) =>
    `<button class="conn" data-go="${go}" title="${esc(name)}: ${esc(tip)}"><span class="dot ${st}"></span><span class="nm">${esc(name)}</span><span class="st">${esc(word)}</span></button>`).join(''));
}
$('conns').addEventListener('click', e => {
  const b = e.target.closest('[data-go]'); if (!b) return;
  show(b.dataset.go);
});

// ---------- workspace ----------
function renderWorkspace() { renderWorkspaceInto($('workspace')); renderWorkspaceInto($('workspace2')); }
function renderWorkspaceInto(box) {
  const w = S.ws;
  $('ws-src').textContent = w?.ok ? (w.source || '') : '';
  if (!w || !w.ok) { box.innerHTML = '<div class="quiet">No workspace yet. Focus a terminal inside a git project, or choose a folder in Preferences.</div>'; emptyState(); return; }
  if (!w.git) { box.innerHTML = `<dl class="kv"><dt>Folder</dt><dd class="mono">${esc(w.path)}</dd></dl><div class="quiet" style="margin-top:6px">Not a git repository.</div>`; return; }
  box.innerHTML = `<dl class="kv"><dt>Project</dt><dd>${esc(w.name)}</dd><dt>Path</dt><dd class="mono" title="${esc(w.path)}">${esc(w.path)}</dd>` +
    `<dt>Branch</dt><dd class="mono">${esc(w.branch)}</dd><dt>Changes</dt><dd>${w.changed ? `${w.changed} uncommitted file${w.changed === 1 ? '' : 's'}` : 'Working tree clean'}</dd>` +
    (w.commit ? `<dt>Last</dt><dd title="${esc(w.commit.subject)}"><span class="mono">${esc(w.commit.hash)}</span> ${esc(w.commit.subject)} <span class="faint">· ${esc(w.commit.when)}</span></dd>` : '') +
    `</dl>` + (w.files?.length ? `<div class="files">${w.files.map(f => `<div>${esc(f)}</div>`).join('')}${w.changed > w.files.length ? `<div class="faint">+ ${w.changed - w.files.length} more</div>` : ''}</div>` : '');
  emptyState();
}

// ---------- brain, route, mic ----------
function renderBrains() {
  const e = S.engine; if (!e) { renderConns(); return; }
  for (const b of document.querySelectorAll('[data-brain]')) {
    const k = b.dataset.brain, info = (e.brains || {})[k] || { ok: false, why: 'unknown', label: k };
    b.classList.toggle('on', e.active === k); b.classList.toggle('loading', e.switching === k);
    b.setAttribute('aria-pressed', e.active === k);
    b.disabled = !S.conn || (!info.ok && e.active !== k);
    b.title = e.active === k ? `${info.label} is active` : info.ok ? `Switch to ${info.label}` : `${info.label} unavailable: ${info.why}`;
  }
  renderConns(); renderRoute();
}
function renderRoute() {
  const e = S.engine, r = $('route');
  if (!S.conn) { r.textContent = 'Not connected to CLOVE: your text stays here until it reconnects.'; return; }
  if (!e || !e.active) { r.textContent = 'No brain available: add GEMINI_API_KEY to .env or install Qwen (see Preferences).'; return; }
  const where = { gemini: `Gemini Live (${S.info?.live_model || 'cloud'})`, hybrid: `Hybrid · ${S.info?.hybrid_models?.[0] || 'Gemini text'}`,
                  qwen: `Qwen on this PC (${S.info?.local_model || 'local'})` }[e.active] || e.active;
  r.textContent = `${where} · Enter sends, Shift+Enter adds a line`;
}
function renderMic() {
  $('mic-tx').textContent = S.muted ? 'Mic off' : 'Mic on'; $('mic').classList.toggle('muted', S.muted);
  $('mic').setAttribute('aria-pressed', !S.muted);
  $('mic').title = (S.muted ? 'Microphone off' : 'Microphone on') + (S.route ? ` · ${S.route.label}` : '') + ' (Ctrl+M)';
  renderConns();
}

// ---------- compact companion ----------
function renderMini() {
  if (!document.body.classList.contains('compact')) return;
  const m = $('mini');
  if (!changed(m, JSON.stringify([S.last, S.plan?.approval === 'pending' && S.plan, jobsKey()]))) return;
  m.textContent = '';
  for (const who of ['you', 'clove']) {
    const l = S.last[who]; if (!l) continue;
    const d = h('div', 'line ' + who, `<span class="ts">${hhmm(l.ts)}</span><div><div class="who">${who === 'you' ? 'You' : 'CLOVE'}</div><div class="said"></div></div>`);
    const b = d.querySelector('.said'); if (who === 'you') b.textContent = l.text.slice(-240); else b.innerHTML = md(l.text.slice(-600));
    m.appendChild(d);
  }
  if (S.plan && S.plan.approval === 'pending') m.appendChild(planCard(S.plan, true));
  running().forEach(a => m.appendChild(jobRow(a)));
  if (!m.children.length) m.appendChild(h('div', 'quiet', `Type below, or say "${esc(wakeWord())}".`));
}
function setCompact(on, fromServer) {
  if (EMBED) return;                                       // Clove Notch's window has its own size
  document.body.classList.toggle('compact', on);
  if (!fromServer) send({ type: 'window', mode: on ? 'compact' : 'expanded' });
  renderMini(); wake();
}
function autoCompact() { if (!EMBED && !S.prefs.compact) document.body.classList.toggle('compact', innerWidth < 520); renderMini(); }
addEventListener('resize', autoCompact);

// ---------- preferences ----------
function sw(key, on, label) { return `<button class="switch" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}" data-set="${key}"></button>`; }
function renderSettings() {
  const i = S.info;
  if (!i) { drawn.delete($('settings')); $('settings').innerHTML = `<div class="card quiet">${S.conn ? 'Loading…' : 'Not connected to CLOVE: preferences show once it is running.'}</div>`; return; }
  const p = i.prefs || {}, e = S.engine || { brains: {} };
  if (!changed($('settings'), JSON.stringify([i, S.engine && { ...S.engine, switching: null }, S.muted, S.route?.label, document.body.classList.contains('compact')]))) { renderBrains(); return; }
  const machines = Object.entries(i.machines || {});
  const voice = i.voice || 'clove';
  $('settings').innerHTML = `
  <div class="label">Brain</div><div class="card">
    <div class="row"><div class="lab">Who listens and answers<small>Unavailable ones say why when you point at them.</small></div>
      <div class="seg" role="group" aria-label="Brain">${['gemini', 'hybrid', 'qwen'].map(k => `<button data-brain="${k}">${esc(e.brains?.[k]?.label || k)}</button>`).join('')}</div></div>
    <div class="row"><div class="lab">Models<small class="mono">Live ${esc(i.live_model)} · Hybrid ${esc((i.hybrid_models || []).join(', '))} · Qwen ${esc(i.local_model)} at ${esc(i.ollama)}</small>
      <small>Set in .env: GEMINI_MODEL, HYBRID_MODELS, LOCAL_MODEL, OLLAMA_HOST. Restart CLOVE after a change.</small></div></div>
    <div class="row"><div class="lab">Gemini API key<small>${i.key ? 'Set in .env. It is never shown here.' : 'Missing: add GEMINI_API_KEY to .env.'}</small></div>
      <button class="btn" data-refresh>Test connections</button></div>
  </div>
  <div class="label">Voice</div><div class="card">
    <div class="row"><div class="lab">Speaking voice</div>
      <div class="seg" role="group" aria-label="Speaking voice"><button data-voice="clove" class="${voice === 'clove' ? 'on' : ''}">Male</button><button data-voice="rose" class="${voice === 'rose' ? 'on' : ''}">Female</button></div></div>
    <div class="row"><div class="lab">Wake word<small>Nothing goes to a brain until you say "${esc((i.wake_names || []).join('" or "'))}". Off: CLOVE always listens.</small></div>${sw('wake', p.wake, 'Wake word')}</div>
    <div class="row"><div class="lab">Microphone<small>${S.route ? esc(S.route.label) : 'Device unknown'}</small></div>${sw('mic', !S.muted, 'Microphone')}</div>
    <div class="row"><div class="lab">Chimes<small>Short sounds when CLOVE hears you and when jobs finish.</small></div>${sw('earcons', p.earcons, 'Chimes')}</div>
    <div class="row"><div class="lab">Read out new messages<small>When WhatsApp, Instagram, X, LinkedIn and the like notify you, CLOVE says who wrote and offers to reply. Not during dictation, focus or a call.</small></div>${sw('announce', p.announce !== false, 'Read out new messages')}</div>
    <div class="row"><div class="lab">Send messages to Telegram when I'm away<small>While the screen is locked, or nothing has moved for a while, new messages also go to your Telegram bot. Needs a Telegram bot of its own (CLOVE_TELEGRAM_BOT_TOKEN) and TELEGRAM_CHAT_ID.</small></div>${sw('forward', p.forward !== false, 'Send messages to Telegram when away')}</div>
    <div class="row"><div class="lab">Reply to messages for me<small>WhatsApp only, never in groups: CLOVE answers new messages briefly as your assistant, says you'll get back to them, and tells you what it sent. It never shares your details or agrees to anything, skips codes, money and companies, and replies to each person at most once every 30 minutes.</small></div>${sw('autoreply', !!p.autoreply, 'Reply to messages for me')}</div>
    <div class="row"><div class="lab">Answer my calls<small>When a call rings on WhatsApp Web, or on your phone while it is connected to this PC over Bluetooth, CLOVE picks up as your assistant, takes a message and keeps talking if they want to. Never money, codes or promises. You hear both sides live, and get a summary on Telegram afterwards (CLOVE's own bot).</small></div>${sw('answercalls', !!p.answercalls, 'Answer my calls')}</div>
    <div class="row"><div class="lab">Talk to callers in Hindi<small>On calls CLOVE speaks natural, everyday Hindi (Hinglish is fine), and switches to English only if the caller does.</small></div>${sw('callhindi', !!p.callhindi, 'Talk to callers in Hindi')}</div>
  </div>
  <div class="label">Window</div><div class="card">
    ${EMBED ? '' : `<div class="row"><div class="lab">Compact companion<small>A small floating window in the bottom-right corner (Ctrl+J). Remembered at the next start.</small></div>${sw('compact', document.body.classList.contains('compact'), 'Compact companion')}</div>
    <div class="row"><div class="lab">Keep on every workspace<small>In compact mode, pin the window so it follows you across Hyprland workspaces.</small></div>${sw('pin', p.pin, 'Keep on every workspace')}</div>`}
    <div class="row"><div class="lab">Reduce motion<small>Stills the bands and the mark. Your system setting is followed too.</small></div>${sw('reduce', !!p.reduce, 'Reduce motion')}</div>
  </div>
  <div class="label">Workspace</div><div class="card">
    <div class="row"><div class="lab">Project folder<small>Empty: follow the git project of your focused terminal.</small></div></div>
    <div class="row"><input class="field mono" id="ws-path" value="${esc(p.workspace || '')}" placeholder="~/Projects/my-app" aria-label="Project folder"><button class="btn" id="ws-save">Save</button><button class="btn" id="ws-clear">Follow terminal</button></div>
  </div>
  <div class="label">Permissions</div><div class="card">
    <div class="row"><div class="lab">Runs commands on<small class="mono">this PC${machines.map(([k, v]) => ` · ${esc(k)} (${esc(v)})`).join('')}</small></div></div>
    <div class="row"><div class="lab">Always asks first<small>Installs, deletes, service restarts, sudo, phone calls, and anything sent or bought on a website. One yes covers a plan for 15 minutes. The backend enforces this, not this window.</small></div></div>
    <div class="row"><div class="lab">sudo<small class="mono">${Object.entries(i.sudo || {}).map(([k, v]) => `${esc(k)}: ${v ? 'password set' : 'not configured'}`).join(' · ')}</small></div></div>
    <div class="row"><div class="lab">Coding agents<small>They edit project files in their own safe modes; system changes come back to CLOVE for approval. Order: <span class="mono">${esc((i.agents || []).join(', '))}</span></small></div></div>
  </div>
  <div class="label">Shortcuts</div><div class="card">
    ${[['Ctrl K', 'Command palette'], ...(EMBED ? [] : [['Ctrl J', 'Compact companion or full window']]), ['Ctrl M', 'Microphone on or off'], ['Esc', 'Stop speaking'],
       ['Ctrl /', 'Focus the message box'], ['Alt B', 'Next brain'], ['Ctrl 1–4', 'Conversation, Activity, Systems, Preferences']]
      .map(([k, d]) => `<div class="row"><div class="lab">${d}</div><kbd>${k}</kbd></div>`).join('')}
  </div>
  <div class="card quiet">CLOVE ${esc(i.version || '')} · starts with your session (systemd user service <span class="mono">clove</span>), see README › Starting with your session.</div>`;
  renderBrains();
}
$('settings').addEventListener('click', e => {
  const s = e.target.closest('[data-set]');
  if (s) {
    const k = s.dataset.set, v = s.getAttribute('aria-checked') !== 'true';
    s.setAttribute('aria-checked', v);
    if (k === 'mic') setMuted(!v); else if (k === 'compact') setCompact(v);
    else if (!send({ type: 'setting', key: k, value: v })) { s.setAttribute('aria-checked', !v); toast('Not connected to CLOVE: the setting was not saved.', 'warn'); }
    return;
  }
  const v = e.target.closest('[data-voice]');
  if (v && send({ type: 'engine', value: 'voice:' + v.dataset.voice })) v.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === v));
  if (e.target.id === 'ws-save') send({ type: 'setting', key: 'workspace', value: $('ws-path').value });
  if (e.target.id === 'ws-clear') { $('ws-path').value = ''; send({ type: 'setting', key: 'workspace', value: '' }); }
});
function applyMotion() { document.body.classList.toggle('reduce', !!S.prefs.reduce); wake(); }

// ---------- systems: on-demand machine checks ----------
function renderChecks() {
  const btns = $('check-btns');
  if (changed(btns, JSON.stringify(Object.keys(S.info?.machines || {})))) { btns.textContent = '';
  [['local', 'This PC'], ...Object.keys(S.info?.machines || {}).map(k => [k, k[0].toUpperCase() + k.slice(1)])].forEach(([k, l]) => {
    const b = h('button', 'btn'); b.textContent = `Check ${l}`;
    b.onclick = () => { if (!send({ type: 'check', what: 'machine_overview', machine: k })) return toast('Not connected to CLOVE.', 'warn');
                        $('check-out').textContent = `Checking ${l}…`; };
    btns.appendChild(b);
  }); }
  if (S.overview) $('check-out').textContent = `${S.overview.text}\n\nChecked at ${hhmm(S.overview.ts)}`;
}

// ---------- notices ----------
function addEvent(m) {
  if (!m.text) return;
  if (S.events.length && S.events[S.events.length - 1].text === m.text) return;
  S.events.push({ ts: m.ts, text: m.text, level: m.level || 'info' }); S.events = S.events.slice(-80);
  if (S.view !== 'activity' && m.ts > S.since) S.unread++;   // replayed old notices don't count
  renderCount(); renderTimeline();
}

// ---------- views & navigation ----------
function show(view, fromParent) {
  if (!VIEWS.includes(view)) view = 'chat';
  if (document.body.classList.contains('compact') && view !== 'chat') setCompact(false);
  S.view = view; store.set('view', view);
  document.querySelectorAll('.side [data-view]').forEach(b => { b.classList.toggle('on', b.dataset.view === view); b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false'); });
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + view));
  if (view === 'activity') { S.unread = 0; renderCount(); renderTimeline(); }
  if (view === 'prefs') renderSettings();
  if (view === 'systems') renderChecks();
  if (EMBED && !fromParent) parent.postMessage({ type: 'clove:view', view }, '*');
  wake();
}
document.querySelectorAll('.side [data-view]').forEach(b => b.onclick = () => show(b.dataset.view));
document.addEventListener('click', e => {
  const b = e.target.closest('[data-brain]'); if (b && !b.disabled && !b.classList.contains('on')) send({ type: 'engine', value: b.dataset.brain });
  if (e.target.closest('[data-refresh]')) { if (send({ type: 'refresh' })) toast('Checking services…'); else toast('Not connected to CLOVE.', 'warn'); }
});
$('to-compact').onclick = () => setCompact(true);
$('to-full').onclick = () => setCompact(false);

// Inside Clove Notch's window: it picks the page and says when the window is hidden (nothing is drawn then).
if (EMBED) {
  document.body.classList.add('embed');
  addEventListener('message', e => {
    if (e.source !== parent || !e.data || typeof e.data !== 'object') return;
    if (e.data.type === 'clove:view') show(String(e.data.view), true);
    if (e.data.type === 'clove:shown') { S.shown = !!e.data.shown; wake(); }
  });
}

// ---------- composer ----------
const input = $('input');
function grow() { input.style.height = 'auto'; input.style.height = Math.min(180, input.scrollHeight) + 'px'; }
function submit() {
  const text = input.value.trim(); if (!text) return;
  const now = Date.now();
  if (text === S.lastSend.text && now - S.lastSend.t < 1500) return;      // a double press
  if (!send({ type: 'text', text })) { toast('Not connected to CLOVE yet. Your text is still in the box.', 'warn'); return; }
  S.lastSend = { text, t: now }; input.value = ''; grow();
}
input.addEventListener('input', grow);
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
$('send').onclick = submit;
$('stop').onclick = () => send({ type: 'stop' });
function setMuted(on) { S.muted = on; send({ type: 'mute', value: on }); store.set('muted', on); renderMic(); }
$('mic').onclick = () => setMuted(!S.muted);

// ---------- command palette ----------
function commands() {
  const compact = document.body.classList.contains('compact');
  const c = [
    ['Go', 'Conversation', () => show('chat'), 'Ctrl 1'], ['Go', 'Activity', () => show('activity'), 'Ctrl 2'],
    ['Go', 'Systems', () => show('systems'), 'Ctrl 3'], ['Go', 'Preferences', () => show('prefs'), 'Ctrl 4'],
    ...(EMBED ? [] : [['Window', compact ? 'Full window' : 'Compact companion', () => setCompact(!compact), 'Ctrl J']]),
    ['Input', 'Focus the message box', () => { show('chat'); input.focus(); }, 'Ctrl /'], ['Voice', S.muted ? 'Turn the microphone on' : 'Turn the microphone off', () => setMuted(!S.muted), 'Ctrl M'],
    ['Voice', 'Listen now', () => send({ type: 'wake' })], ['Voice', 'Stop listening (sleep)', () => send({ type: 'ctl', cmd: 'sleep' })],
    ['Voice', 'Start or stop dictation', () => send({ type: 'ctl', cmd: 'dictate' })],
    ['Focus', 'Focus mode for 25 minutes', () => send({ type: 'ctl', cmd: 'focus 25' })], ['Focus', 'Focus mode for 50 minutes', () => send({ type: 'ctl', cmd: 'focus 50' })],
    ['Systems', 'Test all connections', () => send({ type: 'refresh' })],
    ['Systems', 'Check this PC', () => { show('systems'); send({ type: 'check', what: 'machine_overview', machine: 'local' }); }],
    ...Object.keys(S.info?.machines || {}).map(k => ['Systems', `Check ${k}`, () => { show('systems'); send({ type: 'check', what: 'machine_overview', machine: k }); }]),
  ];
  for (const [k, b] of Object.entries(S.engine?.brains || {})) if (b.ok && S.engine.active !== k) c.push(['Brain', `Switch to ${b.label}`, () => send({ type: 'engine', value: k })]);
  running().forEach(a => c.push(['Jobs', `Cancel: ${a.label}`, () => send({ type: 'cancel_job', id: a.job })]));
  if (S.plan?.approval === 'pending') c.push(['Task', `Approve: ${S.plan.title}`, () => send({ type: 'approve', value: true })], ['Task', `Reject: ${S.plan.title}`, () => send({ type: 'approve', value: false })]);
  return c;
}
let palSel = 0, palItems = [], palFrom = null;
function renderPalette() {
  const q = $('pal-in').value.toLowerCase().trim();
  palItems = commands().filter(([g, l]) => !q || (g + ' ' + l).toLowerCase().includes(q));
  palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
  $('pal-list').innerHTML = palItems.map(([g, l, , k], i) => `<li role="option" aria-selected="${i === palSel}" class="${i === palSel ? 'sel' : ''}" data-i="${i}"><span class="g">${esc(g)}</span>${esc(l)}${k ? `<kbd>${k}</kbd>` : ''}</li>`).join('')
    || '<li class="quiet">No matching command.</li>';
  $('pal-list').querySelector('.sel')?.scrollIntoView({ block: 'nearest' });
}
function openPalette() { palFrom = document.activeElement; $('palette').classList.add('on'); $('pal-in').value = ''; palSel = 0; renderPalette(); $('pal-in').focus(); }
function closePalette() { $('palette').classList.remove('on'); palFrom?.focus?.(); }
function runPalette(i) { const it = palItems[i]; closePalette(); if (it) it[2](); }
$('open-palette').onclick = openPalette;
$('pal-in').addEventListener('input', () => { palSel = 0; renderPalette(); });
$('pal-in').addEventListener('keydown', e => {
  if (e.key === 'ArrowDown') { palSel = Math.min(palItems.length - 1, palSel + 1); renderPalette(); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { palSel = Math.max(0, palSel - 1); renderPalette(); e.preventDefault(); }
  else if (e.key === 'Enter') runPalette(palSel);
  else if (e.key === 'Escape') { e.stopPropagation(); closePalette(); }
});
$('pal-list').addEventListener('click', e => { const li = e.target.closest('li[data-i]'); if (li) runPalette(+li.dataset.i); });
$('palette').addEventListener('click', e => { if (e.target.id === 'palette') closePalette(); });

document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (mod && k === 'k') { e.preventDefault(); $('palette').classList.contains('on') ? closePalette() : openPalette(); }
  else if (mod && k === 'j' && !EMBED) { e.preventDefault(); setCompact(!document.body.classList.contains('compact')); }
  else if (mod && k === 'm') { e.preventDefault(); setMuted(!S.muted); }
  else if (mod && k === '/') { e.preventDefault(); show('chat'); input.focus(); }
  else if (mod && /^[1-4]$/.test(k)) { e.preventDefault(); show(VIEWS[+k - 1]); }
  else if (e.altKey && k === 'b') {
    const order = ['gemini', 'hybrid', 'qwen'].filter(b => S.engine?.brains?.[b]?.ok);
    const next = order[(order.indexOf(S.engine?.active) + 1) % order.length]; if (next) send({ type: 'engine', value: next });
  } else if (k === 'escape' && !$('palette').classList.contains('on') && S.state === 'speaking') send({ type: 'stop' });
});

// ---------- connection ----------
function reset() { feed.textContent = ''; S.acts.clear(); S.cur = {}; S.last = { you: null, clove: null }; S.events = []; }
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws?t=${token}`);
  ws.onopen = () => { S.conn = true; failures = 0; S.since = Date.now() / 1000 - 1; if (S.muted) send({ type: 'mute', value: true }); renderState(); renderBrains(); };
  ws.onclose = () => { S.conn = false; failures++; renderState(); renderBrains(); freshness(); setTimeout(connect, failures > 4 ? 5000 : 1500); };
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    switch (m.type) {
      case 'reset': reset(); emptyState(); break;
      case 'tick':
        if (m.state !== S.state || m.tasks !== S.tasks) { S.state = m.state; S.tasks = m.tasks; renderState(); renderBrains(); }
        S.mic = m.mic; S.out = m.out; onLevels(); break;
      case 'caption': caption(m); break;
      case 'activity': activity(m); break;
      case 'plan': S.plan = m; renderTask(); if (m.approval === 'pending') renderState(); break;
      case 'engine': S.engine = m; renderBrains(); if (S.view === 'prefs') renderSettings(); break;
      case 'report': report(m); break;
      case 'route': S.route = m; renderMic(); break;
      case 'notice': notice = m.text || ''; renderState(); addEvent(m); break;
      case 'toast': if (m.ts > S.since) toast(m.text, m.level); addEvent(m); break;
      case 'telemetry': S.tel = m; renderTelemetry(); break;
      case 'services': S.services = m.items; S.svcChecked = m.checked; renderServices(); break;
      case 'workspace': S.ws = m; renderWorkspace(); break;
      case 'info': S.info = m; S.prefs = m.prefs || {}; applyMotion();
        if (!EMBED) document.body.classList.toggle('compact', !!S.prefs.compact || innerWidth < 520);
        renderMini(); $('ver').textContent = m.version ? 'CLOVE ' + m.version.replace(/-dirty$/, '*') : 'CLOVE';
        $('ver').title = m.version ? `build ${m.version}${m.version.endsWith('-dirty') ? ' (uncommitted changes)' : ''}` : '';
        if (S.view === 'prefs') renderSettings(); if (S.view === 'systems') renderChecks(); renderState(); break;
      case 'window':
        if (EMBED) break;
        document.body.classList.toggle('compact', m.mode === 'compact'); renderMini(); wake();
        if (!m.managed) try { m.mode === 'compact' ? resizeTo(380, 560) : resizeTo(1280, 800); } catch {}
        break;
      case 'overview': S.overview = m; if (S.view === 'systems') renderChecks(); break;
    }
  };
}
setInterval(freshness, 1000);

// ---------- start ----------
document.querySelectorAll('.hero').forEach(el => backdrop(el.querySelector('canvas.backdrop'), el.dataset.color));
presence($('presence'));
requestAnimationFrame(() => stillMark($('logo'), 11, 0.35));
S.muted = store.get('muted', false);
show(params.get('view') || store.get('view', 'chat'), true);
renderState(); renderMic(); renderTask(); renderJobs(); renderWorkspace(); renderSettings(); emptyState(); autoCompact();
connect();

// Inside Clove Notch: say the page loaded, so the notch stops retrying (it reloads an error page every 5 s).
if (EMBED) parent.postMessage({ type: 'clove:ready' }, '*');

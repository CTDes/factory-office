/* factory-office · Canvas renderer and page UI.
 * Reads the office only through OfficeModel and gets data only through OfficeClient, so this file
 * is the one to replace with a Phaser + Tiled scene later. */
(() => {
  "use strict";
  const M = self.OfficeModel;
  const W = 320, H = 112;
  const reduced = self.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- palette
  const P = {
    wall: "#3a3352", wallLine: "#342e4a", trim: "#241f33", floorA: "#5b4535", floorB: "#523e30",
    frame: "#241f33", sky: "#172345", star: "#f4e9c8", moon: "#f6e7a6",
    signBg: "#e9c46a", signInk: "#2a1f12", signShadow: "#9c7a32", labelBg: "#241f33", labelInk: "#b9b1cf",
    metal: "#9aa3b5", metalDark: "#5d6475", dark: "#1a1724", screen: "#47d1b5", screenOff: "#14302f",
    white: "#efe9dc", red: "#e5584b", redDim: "#4a2026", amber: "#f2b84b", amberDim: "#4a3a1c",
    green: "#79c16d", greenDim: "#203a25", shadow: "#2c2230", pot: "#a5573a", leaf: "#4f9a55",
    leafDark: "#2f6b3b", glass: "#6f86ad", carpet: "#40324f", carpetDot: "#4a3a5b",
    deskTop: "#b77d4f", deskFront: "#8c5a37", deskEdge: "#6d4329", monitor: "#2a2735",
    chair: "#6d5c8f", chairDark: "#57497a", belt: "#4a4560", tray: "#3c4a63", cab: "#5f6c82",
    cabFront: "#76849b", manila: "#e8c98a", manilaDark: "#b9975a", specFolder: "#9fb7e8",
    ink: "#2a1f12", skin: "#f0c39a", eye: "#2a1f12", leg: "#2f3348", shoe: "#14121b",
    hair: "#3b2a20", bubble: "#efe9dc"
  };
  const RISK = { low: P.green, medium: P.amber, high: P.red };
  const STAGE_COLOR = {
    "intake": "#6fa8e8", "needs-info": "#b48cf0", "build": "#e08a3c", "gate": "#5fd0c8",
    "review": "#5fae6a", "merging": "#8fa3ff", "ready": "#79c16d", "needs-human": "#e5584b",
    "done": "#7d778f", "rejected": "#8a4d55", "building": "#8fa3ff", "final-review": "#5fae6a",
    "final-build": "#e08a3c"
  };
  const stageColor = s => STAGE_COLOR[s] || "#9c95ae";

  // ---------------------------------------------------------------- 3x5 pixel font
  const FONT = {};
  ("A010101111101101 B110101110101110 C011100100100011 D110101101101110 E111100110100111 F111100110100100 " +
   "G011100101101011 H101101111101101 I111010010010111 J001001001101010 K101101110101101 L100100100100111 " +
   "M101111111101101 N110101101101101 O010101101101010 P110101110100100 Q010101101110011 R110101110101101 " +
   "S011100010001110 T111010010010010 U101101101101111 V101101101101010 W101101111111101 X101101010101101 " +
   "Y101101010010010 Z111001010100111 0111101101101111 1010110010010111 2110001010100111 3110001010001110 " +
   "4101101111001001 5111100110001110 6011100111101111 7111001010010010 8111101111101111 9111101111001110 " +
   "#101111101111101 -000000111000000 ?110001010000010 !010010010000010 .000000000000010 :000010000010000 " +
   "/001001010100100 (010100100100010 )010001001001010 _000000000000111")
    .split(" ").forEach(s => { FONT[s[0]] = s.slice(1); });
  FONT[" "] = "000000000000000";
  const clean = s => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  const tw = s => clean(s).length * 4 - 1;
  function txt(ctx, s, x, y, col) {
    ctx.fillStyle = col;
    for (const ch of clean(s)) {
      const g = FONT[ch] || FONT["?"];
      for (let i = 0; i < 15; i++) if (g[i] === "1") ctx.fillRect(x + (i % 3), y + ((i / 3) | 0), 1, 1);
      x += 4;
    }
  }
  const R = (ctx, x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(x, y, w, h); };
  function label(ctx, s, x, y) { R(ctx, x - 2, y - 1, tw(s) + 4, 7, P.labelBg); txt(ctx, s, x, y, P.labelInk); }

  // ---------------------------------------------------------------- sprites
  const BODY = ["..hhh..", ".hhhhh.", ".sssss.", ".seses.", ".sssss.", "..bbb..", ".bbbbb.", "sbbdbbs", ".bbbbb."];
  const LEGS = [[".l...l.", ".k...k."], ["..l.l..", "..k.k.."]];
  function drawChar(ctx, fx, fy, hat, body, frame, bob) {
    const rows = BODY.concat(LEGS[frame]);
    const map = { h: hat, s: P.skin, e: P.eye, b: body, d: P.trim, l: P.leg, k: P.shoe };
    const x0 = Math.round(fx) - 3, y0 = Math.round(fy) - 11 + bob;
    rows.forEach((row, r) => {
      for (let c = 0; c < row.length; c++) {
        if (row[c] !== ".") { ctx.fillStyle = map[row[c]]; ctx.fillRect(x0 + c, y0 + r, 1, 1); }
      }
    });
  }
  function drawFolder(ctx, job, x, y, selected, now) {
    x = Math.round(x); y = Math.round(y);
    R(ctx, x, y, 5, 2, RISK[job.risk] || P.manilaDark);
    R(ctx, x, y + 1, 12, 7, job.kind === "spec" ? P.specFolder : P.manila);
    R(ctx, x, y + 7, 12, 1, P.manilaDark);
    const s = job.issue != null ? String(job.issue % 1000) : "?";
    txt(ctx, s, x + 1 + Math.floor((11 - tw(s)) / 2), y + 2, P.ink);
    if (selected && Math.floor(now / 300) % 2 === 0) {
      ctx.strokeStyle = P.amber; ctx.lineWidth = 1; ctx.strokeRect(x - 1.5, y - 0.5, 15, 10);
    }
  }
  function bubble(ctx, x, y, ch, col) {
    x = Math.round(x); y = Math.round(y);
    R(ctx, x, y, 7, 7, P.bubble); R(ctx, x + 1, y + 7, 2, 1, P.bubble); R(ctx, x + 1, y + 8, 1, 1, P.bubble);
    txt(ctx, ch, x + 2, y + 1, col);
  }
  function desk(ctx, x, y, w) {
    R(ctx, x, y, w, 3, P.deskTop); R(ctx, x, y + 3, w, 8, P.deskFront); R(ctx, x, y + 3, w, 1, P.deskEdge);
    R(ctx, x + 1, y + 11, 2, 4, P.deskEdge); R(ctx, x + w - 3, y + 11, 2, 4, P.deskEdge);
  }
  function monitor(ctx, x, y) { R(ctx, x, y, 10, 8, P.monitor); R(ctx, x + 1, y + 1, 8, 6, P.screenOff); R(ctx, x + 4, y + 8, 2, 1, P.monitor); }

  // ---------------------------------------------------------------- room geometry
  const SEATS = { planner: { x: 37, y: 48 }, b0: { x: 82, y: 48 }, b1: { x: 124, y: 48 }, reviewer: { x: 219, y: 48 }, boss: { x: 300, y: 62 } };
  const CORR = 36, COFFEE = { x: 49, y: 37 };
  const CHAIRS = [6, 20, 34];
  const ARCHIVE = { x: 152, y: 80 }, TRASH = { x: 189, y: 90 };

  function drawBackground(ctx, sign) {
    R(ctx, 0, 0, W, 24, P.wall);
    for (let x = 6; x < W; x += 12) R(ctx, x, 0, 1, 22, P.wallLine);
    R(ctx, 0, 22, W, 2, P.trim);
    for (let y = 24; y < H; y += 8) for (let x = 0; x < W; x += 8) R(ctx, x, y, 8, 8, ((x + y) / 8) % 2 ? P.floorA : P.floorB);
    R(ctx, 264, 24, 56, 88, P.carpet);
    for (let y = 27; y < H; y += 6) for (let x = 267 + (y % 12 ? 3 : 0); x < W; x += 6) R(ctx, x, y, 1, 1, P.carpetDot);
    R(ctx, 262, 0, 2, 24, P.trim); R(ctx, 262, 24, 2, 46, P.glass); R(ctx, 262, 92, 2, 20, P.glass);
    let name = sign;  // the room's sign hangs between the coffee machine and the window
    while (tw(name) + 6 > 84 && name.length > 4) name = name.slice(0, -1);
    const sw = tw(name) + 6, sx = 58 + Math.floor((84 - sw) / 2);
    R(ctx, sx, 3, sw, 9, P.signBg); R(ctx, sx, 11, sw, 1, P.signShadow); txt(ctx, name, sx + 3, 5, P.signInk);
    R(ctx, 144, 2, 30, 12, P.frame); R(ctx, 145, 3, 28, 10, P.sky); R(ctx, 158, 3, 1, 10, P.frame);
    [[148, 5], [152, 9], [162, 6], [170, 10], [155, 4]].forEach(([x, y]) => R(ctx, x, y, 1, 1, P.star));
    R(ctx, 166, 5, 3, 3, P.moon);
    label(ctx, "RECEPTION", 6, 16); label(ctx, "WORKSHOP", 76, 16); label(ctx, "QA", 152, 16);
    label(ctx, "REVIEW", 198, 16); label(ctx, "HUMAN", 268, 16);
    R(ctx, 43, 6, 12, 3, P.metalDark); R(ctx, 44, 8, 10, 25, P.metal); R(ctx, 46, 11, 6, 3, P.screen);
    R(ctx, 48, 18, 2, 3, P.metalDark); R(ctx, 47, 22, 4, 4, P.white); R(ctx, 52, 15, 1, 1, P.red); R(ctx, 44, 33, 10, 1, P.shadow);
    R(ctx, 226, 26, 8, 7, P.pot); R(ctx, 225, 25, 10, 2, P.pot);
    [[229, 14, 2, 11], [226, 17, 3, 6], [231, 16, 3, 7], [224, 20, 3, 4], [233, 19, 3, 4]].forEach(([x, y, w, h], i) => R(ctx, x, y, w, h, i % 2 ? P.leafDark : P.leaf));
    R(ctx, 212, 3, 9, 9, P.white); R(ctx, 216, 5, 1, 3, P.ink); R(ctx, 216, 7, 3, 1, P.ink);
    R(ctx, 236, 1, 20, 22, P.metalDark); R(ctx, 237, 4, 9, 19, P.metal); R(ctx, 247, 4, 8, 19, P.metal); R(ctx, 246, 4, 1, 19, P.dark);
    R(ctx, 242, 1, 8, 2, P.dark);
    R(ctx, 136, 56, 44, 8, P.dark); R(ctx, 136, 56, 44, 2, P.belt); R(ctx, 138, 64, 2, 6, P.metalDark); R(ctx, 176, 64, 2, 6, P.metalDark);
    R(ctx, 185, 30, 2, 26, P.metalDark); R(ctx, 182, 18, 8, 14, P.dark);
    R(ctx, 140, 82, 36, 26, P.cab);
    for (let i = 0; i < 3; i++) { R(ctx, 142, 85 + i * 7, 32, 5, P.cabFront); R(ctx, 156, 87 + i * 7, 4, 1, P.metalDark); }
    R(ctx, 189, 95, 12, 2, P.metal); R(ctx, 190, 97, 10, 11, P.metalDark); R(ctx, 192, 99, 1, 7, P.dark); R(ctx, 197, 99, 1, 7, P.dark);
    CHAIRS.forEach(x => { R(ctx, x + 1, 86, 10, 8, P.chairDark); R(ctx, x, 94, 12, 3, P.chair); R(ctx, x + 1, 97, 1, 5, P.chairDark); R(ctx, x + 10, 97, 1, 5, P.chairDark); });
    label(ctx, "WAITING", 6, 106);
    R(ctx, 234, 94, 26, 2, P.metalDark); R(ctx, 234, 96, 26, 7, P.tray); R(ctx, 235, 103, 2, 4, P.metalDark); R(ctx, 257, 103, 2, 4, P.metalDark);
    label(ctx, "OUTBOX", 236, 106);
    R(ctx, 298, 1, 8, 2, P.metalDark);
  }

  // ---------------------------------------------------------------- DOM helpers (no innerHTML: CSP-friendly)
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
    return el;
  }
  const $ = id => document.getElementById(id);
  const fmt = ts => {
    const d = new Date(ts);
    if (isNaN(d)) return ts;
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };

  // ---------------------------------------------------------------- state
  const model = M.createModel();
  const views = new Map();         // repo name -> room view
  let selectedKey = null;
  let feed = [];
  let detailEvents = { key: null, rows: [] };

  function makeAgents() {
    return [
      { role: "planner", seat: SEATS.planner },
      { role: "builder", seat: SEATS.b0, k: 0 },
      { role: "builder", seat: SEATS.b1, k: 1 },
      { role: "reviewer", seat: SEATS.reviewer }
    ].map(a => Object.assign(a, { x: a.seat.x, y: a.seat.y, path: [], job: null, coffee: false, wait: 0, walkT: 0 }));
  }

  function ensureView(name) {
    if (views.has(name)) return views.get(name);
    const canvas = h("canvas", { width: W, height: H, role: "img", "aria-label": `Office of ${name}. The active jobs list on the right has the same information.` });
    const wrap = h("div", { class: "canvas-wrap" }, canvas);
    const machinesEl = h("span", { class: "machines" });
    const metaEl = h("span", { class: "meta" });
    const specsEl = h("div", { class: "room-specs", hidden: true });
    const el = h("article", { class: "room" },
      h("div", { class: "room-head" }, h("h2", {}, name), machinesEl, metaEl), specsEl, wrap);
    const view = {
      name, el, canvas, ctx: canvas.getContext("2d"), machinesEl, metaEl, specsEl,
      bg: document.createElement("canvas"), agents: makeAgents(), pos: new Map(), leaving: new Map(),
      flash: null, coffeeBusy: false
    };
    view.bg.width = W; view.bg.height = H;
    drawBackground(view.bg.getContext("2d"), name.split("/").pop());
    const fit = () => {
      const w = wrap.clientWidth || 640;
      const s = w >= 640 ? Math.min(4, Math.floor(w / W)) : w / W;
      canvas.style.width = W * s + "px"; canvas.style.height = H * s + "px";
    };
    new ResizeObserver(fit).observe(wrap); fit();
    const pick = ev => {
      const r = canvas.getBoundingClientRect();
      const x = (ev.clientX - r.left) / r.width * W, y = (ev.clientY - r.top) / r.height * H;
      for (const [key, p] of view.pos) if (x >= p.x - 1 && x <= p.x + 13 && y >= p.y - 1 && y <= p.y + 9) return key;
      for (const a of view.agents) if (a.job && Math.abs(x - a.x) <= 4 && y >= a.y - 12 && y <= a.y) return a.job.key;
      return null;
    };
    canvas.addEventListener("click", ev => { const k = pick(ev); if (k) select(k); });
    canvas.addEventListener("mousemove", ev => { canvas.style.cursor = pick(ev) ? "pointer" : "default"; });
    views.set(name, view);
    const rooms = $("rooms");
    const after = [...views.keys()].sort().indexOf(name);
    rooms.insertBefore(el, rooms.children[after] || null);
    return view;
  }

  // ---------------------------------------------------------------- layout: where each folder and agent goes
  function layout(view, repo, now) {
    const jobs = M.liveJobs(repo);
    const targets = new Map();
    const byZone = {};
    for (const j of jobs) {
      const p = M.placeFor(j);
      (byZone[p.zone] = byZone[p.zone] || []).push(Object.assign({ job: j }, p));
    }
    const take = z => byZone[z] || [];
    const claimAt = e => (e.job.claim && e.job.claim.at) || e.job.ts;
    const assigned = { planner: null, b0: null, b1: null, reviewer: null, gate: null };

    take("reception").forEach((e, i) => {
      if (e.working && !assigned.planner) assigned.planner = e.job;
      targets.set(e.job.key, { x: 8 + (i % 2) * 13, y: 34 - Math.floor(i / 2) * 3 });
    });
    take("waiting").forEach((e, i) => targets.set(e.job.key, { x: CHAIRS[i % 3], y: 86 - Math.floor(i / 3) * 3 }));
    const builds = take("workshop").slice().sort((a, b) => (b.working - a.working) || (claimAt(a) < claimAt(b) ? -1 : 1));
    let queue = 0;
    builds.forEach(e => {
      if (e.working && !assigned.b0) { assigned.b0 = e.job; targets.set(e.job.key, { x: 64, y: 34 }); }
      else if (e.working && !assigned.b1) { assigned.b1 = e.job; targets.set(e.job.key, { x: 106, y: 34 }); }
      else { targets.set(e.job.key, { x: 56 + (queue % 5) * 14, y: 66 + Math.floor(queue / 5) * 3 }); queue++; }
    });
    let gq = 0;
    take("qa").forEach(e => {
      if (e.working && !assigned.gate) {
        assigned.gate = e.job;
        const started = Date.parse(claimAt(e));
        const p = isNaN(started) ? 0.5 : Math.min(0.95, (Date.now() - started) / 120000);
        targets.set(e.job.key, { x: 136 + 30 * p, y: 48 });
      } else { targets.set(e.job.key, { x: 120 - (gq % 3) * 14, y: 82 - Math.floor(gq / 3) * 3 }); gq++; }
    });
    let rq = 0;
    take("review").forEach(e => {
      if (e.working && !assigned.reviewer) { assigned.reviewer = e.job; targets.set(e.job.key, { x: 194, y: 34 }); }
      else { targets.set(e.job.key, { x: 194 + (rq % 3) * 14, y: 66 + Math.floor(rq / 3) * 3 }); rq++; }
    });
    take("elevator").forEach((e, i) => targets.set(e.job.key, { x: 240, y: 26 + i * 3 }));
    take("outbox").forEach((e, i) => targets.set(e.job.key, { x: 236 + (i % 2) * 12, y: 86 - Math.floor(i / 2) * 3 }));
    take("boss").forEach((e, i) => targets.set(e.job.key, { x: 272 + (i % 2) * 13, y: 48 - Math.floor(i / 2) * 3 }));
    take("hall").forEach((e, i) => targets.set(e.job.key, { x: 96 + i * 14, y: 92 }));

    const a = view.agents;
    a[0].job = assigned.planner; a[1].job = assigned.b0; a[2].job = assigned.b1; a[3].job = assigned.reviewer;
    return { targets, gateJob: assigned.gate, alarm: take("boss").length > 0, merging: take("elevator").length > 0, jobs };
  }

  // ---------------------------------------------------------------- agents
  const atSeat = a => !a.path.length && Math.abs(a.x - a.seat.x) < .5 && Math.abs(a.y - a.seat.y) < .5;
  function sendHome(a) {
    a.path = a.y < 41 ? [{ x: a.seat.x, y: CORR }, { x: a.seat.x, y: a.seat.y }] : [{ x: a.seat.x, y: a.seat.y }];
  }
  function stepAgents(view, dt) {
    for (const a of view.agents) {
      if (a.path.length) {
        const p = a.path[0], dx = p.x - a.x, dy = p.y - a.y, d = Math.hypot(dx, dy), s = 24 * dt;
        if (d <= s) { a.x = p.x; a.y = p.y; a.path.shift(); } else { a.x += dx / d * s; a.y += dy / d * s; }
        a.walkT += dt;
        continue;
      }
      if (a.coffee) {
        a.wait -= dt;
        if (a.wait <= 0 || a.job) { a.coffee = false; view.coffeeBusy = false; sendHome(a); }
        continue;
      }
      if (a.job && !atSeat(a)) { sendHome(a); continue; }
      if (!a.job && !reduced && atSeat(a) && !view.coffeeBusy && Math.random() < .02 * dt) {
        view.coffeeBusy = true; a.coffee = true; a.wait = 3 + Math.random() * 4;
        a.path = [{ x: a.seat.x, y: CORR }, { x: COFFEE.x, y: CORR }, { x: COFFEE.x, y: COFFEE.y }];
      }
    }
  }

  // ---------------------------------------------------------------- drawing
  function draw(view, repo, now, dt) {
    const ctx = view.ctx;
    const L = layout(view, repo, now);
    stepAgents(view, dt);
    ctx.drawImage(view.bg, 0, 0);
    const blink = Math.floor(now / 400) % 2 === 0;
    R(ctx, 243, 1, 6, 2, L.merging && blink ? P.amber : P.dark);
    const off = L.gateJob && !reduced ? Math.floor(now / 90) % 4 : 0;
    for (let x = 136 + off; x < 180; x += 4) R(ctx, x, 60, 2, 1, P.metalDark);
    const fl = view.flash && view.flash.until > now ? view.flash.c : null;
    R(ctx, 184, 20, 4, 3, fl === "fail" ? P.red : P.redDim);
    R(ctx, 184, 24, 4, 3, !fl && L.gateJob && blink ? P.amber : P.amberDim);
    R(ctx, 184, 28, 4, 3, fl === "pass" ? P.green : P.greenDim);
    R(ctx, 299, 3, 6, 4, L.alarm && blink ? P.red : P.redDim);
    if (L.alarm && blink && !reduced) { ctx.fillStyle = "rgba(229,88,75,0.13)"; ctx.fillRect(264, 0, 56, H); }
    label(ctx, "ARCHIVE " + repo.done, 142, 76);
    if (repo.rejected) txt(ctx, String(repo.rejected), 194, 89, P.labelInk);

    for (const a of view.agents) {
      const frame = a.path.length && !reduced ? Math.floor(a.walkT * 6) % 2 : 0;
      const working = a.job && atSeat(a);
      const bob = working && !reduced && Math.floor(now / 260 + a.seat.x) % 2 ? 1 : 0;
      const hat = M.hatColor(a.job, a.role);
      drawChar(ctx, a.x, a.y, hat, M.SHIRT_COLORS[a.role], frame, bob);
    }
    drawChar(ctx, SEATS.boss.x, SEATS.boss.y, P.hair, M.SHIRT_COLORS.boss, 0, L.alarm && blink && !reduced ? 1 : 0);

    desk(ctx, 6, 42, 36); desk(ctx, 52, 42, 36); desk(ctx, 94, 42, 36); desk(ctx, 192, 42, 36); desk(ctx, 270, 56, 40);
    monitor(ctx, 54, 33); monitor(ctx, 96, 33); monitor(ctx, 296, 47);
    R(ctx, 306, 48, 3, 4, P.white); R(ctx, 309, 49, 1, 2, P.white);
    R(ctx, 30, 38, 5, 4, P.white); R(ctx, 31, 39, 3, 1, P.labelBg); R(ctx, 31, 41, 3, 1, P.labelBg);
    R(ctx, 208, 40, 6, 2, P.redDim);
    view.agents.filter(a => a.role === "builder").forEach(a => {
      if (!(a.job && atSeat(a))) return;
      const mx = a.k ? 97 : 55, seed = reduced ? 3 : Math.floor(now / 160) + a.k * 7;
      for (let row = 0; row < 3; row++) {
        const len = 2 + ((seed * (row + 3) * 37) % 6);
        R(ctx, mx + (row % 2), 35 + row * 2, Math.min(7, len), 1, P.screen);
      }
    });
    const rv = view.agents[3];
    if (rv.job && atSeat(rv)) { const up = !reduced && Math.floor(now / 350) % 2; R(ctx, 209, up ? 34 : 37, 3, 3, P.red); R(ctx, 210, up ? 32 : 35, 1, 2, P.deskEdge); }

    const k = Math.min(1, dt * 6);
    for (const key of [...view.pos.keys()]) if (!L.targets.has(key) && !view.leaving.has(key)) view.pos.delete(key);
    for (const j of L.jobs) {
      const t = L.targets.get(j.key); if (!t) continue;
      let p = view.pos.get(j.key);
      if (!p) { p = { x: t.x, y: t.y }; view.pos.set(j.key, p); }
      p.x += (t.x - p.x) * k; p.y += (t.y - p.y) * k;
      drawFolder(ctx, j, p.x, p.y, j.key === selectedKey, now);
      if (j.stage === "needs-info") bubble(ctx, p.x + 3, p.y - 10 + (blink && !reduced ? 0 : 1), "?", "#7a4fc9");
    }
    for (const [key, l] of view.leaving) {
      const p = view.pos.get(key) || { x: 120, y: 60 };
      const t = l.job.stage === "rejected" ? TRASH : ARCHIVE;
      p.x += (t.x - p.x) * k; p.y += (t.y - p.y) * k; view.pos.set(key, p);
      drawFolder(ctx, l.job, p.x, p.y, false, now);
      if (now > l.until) { view.leaving.delete(key); view.pos.delete(key); }
    }
    if (L.alarm) bubble(ctx, SEATS.boss.x - 3, 40 + (blink ? 0 : 1), "!", P.red);
  }

  // ---------------------------------------------------------------- page sections
  function renderHeaders() {
    for (const [name, repo] of Object.entries(model.repos)) {
      const view = ensureView(name);
      const live = M.liveJobs(repo).length;
      view.machinesEl.textContent = Object.entries(repo.machines).map(([m, t]) => `${m} · ${fmt(t)}`).join("   ");
      view.metaEl.textContent = `${live} active · ${repo.done} done${repo.rejected ? ` · ${repo.rejected} rejected` : ""}`;
      const specs = M.specs(repo);
      view.specsEl.hidden = specs.length === 0;
      view.specsEl.replaceChildren(...specs.map(s =>
        h("span", {}, "spec ", h("button", { type: "button", onclick: () => select(s.job.key) }, `#${s.job.issue} ${s.job.title}`),
          ` · ${s.job.stage} · ${s.done}/${s.total} tickets done`)));
    }
    $("empty").hidden = Object.keys(model.repos).length > 0;
  }

  function renderChips() {
    const c = M.counts(model);
    $("chips").replaceChildren(
      ...M.STAGES.filter(s => c[s]).map(s => h("span", { class: "chip" + (s === "needs-human" ? " hot" : ""), style: { "--c": stageColor(s) } }, h("i"), s, " ", h("b", {}, c[s]))),
      h("span", { class: "chip", style: { "--c": stageColor("done") } }, h("i"), "done ", h("b", {}, c.done)));
  }

  function eventRow(e, fresh) {
    return h("li", { class: fresh ? "new" : null },
      h("span", { class: "t" }, fmt(e.ts)), h("span", {}, e.repo), h("span", {}, e.job_id.slice(0, 3)),
      h("span", {}, `${e.from} → `, h("span", { style: { color: stageColor(e.to) } }, e.to)),
      h("span", { class: "why", title: e.reason }, e.reason));
  }
  function renderFeed(freshSeq) {
    $("feed").replaceChildren(...feed.slice(0, 200).map(e => eventRow(e, e.seq === freshSeq)));
  }

  function findJob(key) {
    for (const repo of Object.values(model.repos)) for (const j of Object.values(repo.jobs)) if (j.key === key) return j;
    return null;
  }

  function who(job) {
    const p = M.placeFor(job);
    if (p.working) return `${job.claim.action} running since ${fmt(job.claim.at)}`;
    switch (job.stage) {
      case "ready": return "waiting for a human to review and merge the PR";
      case "needs-human": return "waiting for a human: " + (job.reason || "see the issue");
      case "needs-info": return "waiting for an answer on the issue";
      case "done": case "rejected": return "finished";
      default: return "waiting for its turn";
    }
  }

  function select(key) {
    selectedKey = key;
    renderPanel();
    const job = findJob(key);
    if (job) loadDetailEvents(job);
  }

  async function loadDetailEvents(job) {
    try {
      const rows = await client.fetchEvents({ repo: job.repo, job_id: job.id, last: 8 });
      if (selectedKey === job.key) { detailEvents = { key: job.key, rows }; renderPanel(); }
    } catch (e) { /* the stream status already shows connection problems */ }
  }

  function renderPanel() {
    const job = selectedKey ? findJob(selectedKey) : null;
    const detail = $("detail");
    if (!job) {
      detail.replaceChildren(h("p", { class: "hint" }, "Click a folder or a person in the office, or pick a job from the list."));
    } else {
      const links = M.links(job);
      const kv = [
        ["id", job.id], ["now", who(job)], ["kind", job.kind],
        ["risk", job.risk || "—"],
        ["models", Object.entries(job.models).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"],
        ["branch", job.branch || "—"], ["base", job.base || "—"], ["machine", job.machine],
        ["updated", fmt(job.ts)]
      ];
      const linkRow = [];
      if (links.issue) linkRow.push(h("a", { href: links.issue, target: "_blank", rel: "noopener noreferrer" }, `issue #${job.issue}`));
      if (links.pr) linkRow.push(" · ", h("a", { href: links.pr, target: "_blank", rel: "noopener noreferrer" }, `PR #${job.pr}`));
      const rows = detailEvents.key === job.key ? detailEvents.rows : [];
      detail.replaceChildren(
        h("div", { class: "repo" }, job.repo),
        h("h4", {}, job.issue != null ? `#${job.issue} ${job.title}` : job.title),
        h("span", { class: "pill", style: { "--c": stageColor(job.stage) } }, job.stage + (job.round > 1 ? ` · round ${job.round}` : "")),
        linkRow.length ? h("div", {}, linkRow) : null,
        h("dl", { class: "kv" }, kv.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
        job.snapshot ? null : h("p", { class: "hint" }, "Only transitions are known for this job: its job.json has not arrived yet."),
        h("div", {}, h("div", { class: "repo" }, "events.log"),
          h("ul", { class: "ev" }, rows.slice().reverse().map(e => h("li", {}, `${fmt(e.ts)} `, h("b", {}, `${e.from} → ${e.to}`), ` ${e.reason}`)))));
    }
    const list = [];
    for (const name of Object.keys(model.repos).sort()) {
      const jobs = M.liveJobs(model.repos[name]).sort((a, b) => M.STAGES.indexOf(b.stage) - M.STAGES.indexOf(a.stage) || (a.issue || 0) - (b.issue || 0));
      if (!jobs.length) continue;
      list.push(h("li", { class: "grp" }, name));
      for (const j of jobs) {
        list.push(h("li", {}, h("button", { type: "button", "aria-current": String(j.key === selectedKey), onclick: () => select(j.key) },
          h("i", { class: "d", style: { "--c": stageColor(j.stage) } }), h("span", { class: "n" }, `#${j.issue}`),
          h("span", { class: "tt" }, j.title), h("span", { class: "st" }, j.stage + (M.placeFor(j).working ? " ●" : "")))));
      }
    }
    $("joblist").replaceChildren(...(list.length ? list : [h("li", { class: "hint" }, "No active jobs.")]));
  }

  function renderAll(freshSeq) { renderHeaders(); renderChips(); renderFeed(freshSeq); renderPanel(); }

  // ---------------------------------------------------------------- data
  const client = new OfficeClient({
    onStatus(s) {
      const el = $("status");
      el.dataset.state = s;
      el.textContent = { connecting: "connecting", live: "live", retrying: "reconnecting", auth: "token needed" }[s] || s;
      const auth = s === "auth";
      $("login").hidden = !auth;
      $("main").hidden = auth;
      $("signout").hidden = auth;
      $("login-error").hidden = !(auth && client.token);
    },
    async onState(state) {
      M.loadState(model, state);
      try { feed = (await client.fetchEvents({ last: 80 })).reverse(); } catch (e) { feed = []; }
      renderAll();
      const job = selectedKey && findJob(selectedKey);
      if (job) loadDetailEvents(job);
    },
    onMessage(msg) {
      const repoBefore = model.repos[msg.event.repo];
      const old = repoBefore && repoBefore.jobs[msg.event.job_id];
      const out = M.applyMessage(model, msg);
      const view = ensureView(msg.event.repo);
      if (out.gate) view.flash = { c: out.gate, until: performance.now() + 1500 };
      if (out.job && M.FINISHED.indexOf(out.job.stage) >= 0 && old && M.FINISHED.indexOf(old.stage) < 0) {
        view.leaving.set(out.job.key, { job: out.job, until: performance.now() + 1600 });
      }
      feed.unshift(out.event);
      if (feed.length > 300) feed.length = 300;
      renderAll(out.event.seq);
      if (out.job && out.job.key === selectedKey) loadDetailEvents(out.job);
    }
  });

  $("login").addEventListener("submit", ev => {
    ev.preventDefault();
    client.setToken($("token").value);
    $("token").value = "";
    client.start();
  });
  $("signout").addEventListener("click", () => client.forget());

  let last = performance.now();
  function loop(now) {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    for (const [name, view] of views) if (model.repos[name]) draw(view, model.repos[name], now, dt);
    $("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  setInterval(renderHeaders, 30000);
  client.start();
})();

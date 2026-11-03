/* factory-office · model: pure functions over /state and /stream data. No DOM, no network.
 * Works as a browser global (window.OfficeModel) and as a CommonJS module (node --test).
 * Any renderer (Canvas today, Phaser later) reads the office through these functions only. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OfficeModel = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FINISHED = ["done", "rejected"];
  /* Display order of live stages, most urgent last so humans see it at the end of a list. */
  const STAGES = ["intake", "needs-info", "build", "gate", "review", "merging",
    "final-build", "final-review", "ready", "needs-human"];

  function createModel() {
    return { repos: {}, seq: 0 };
  }

  function room(model, name) {
    if (!model.repos[name]) model.repos[name] = { name, machines: {}, jobs: {}, done: 0, rejected: 0 };
    return model.repos[name];
  }

  function normalizeJob(row) {
    const snap = row.job || {};
    return {
      key: row.repo + "#" + row.job_id,
      repo: row.repo,
      id: row.job_id,
      kind: row.kind || snap.kind || "ticket",
      issue: row.issue != null ? row.issue : (snap.issue != null ? snap.issue : null),
      spec: row.spec || snap.spec || null,
      stage: row.stage,
      ts: row.ts,
      machine: row.machine,
      title: snap.title || row.job_id,
      round: snap.round || 0,
      risk: snap.risk || null,
      pr: snap.pr || null,
      models: snap.models || {},
      claim: snap.claim || null,
      reason: snap.reason || null,
      surfaces: snap.surfaces || [],
      branch: snap.branch || null,
      base: snap.base || null,
      tickets: snap.tickets || null,
      snapshot: row.job ? true : false
    };
  }

  function recount(r) {
    r.done = 0; r.rejected = 0;
    for (const j of Object.values(r.jobs)) {
      if (j.stage === "done") r.done++;
      else if (j.stage === "rejected") r.rejected++;
    }
  }

  /* Replace everything with a GET /state answer. */
  function loadState(model, state) {
    model.repos = {};
    for (const r of state.repos || []) room(model, r.repo).machines[r.machine] = r.last_seen;
    for (const row of state.jobs || []) room(model, row.repo).jobs[row.job_id] = normalizeJob(row);
    Object.values(model.repos).forEach(recount);
    model.seq = state.seq || 0;
    return model;
  }

  /* Fold one /stream message ({event, job, repos}) in. Returns what changed, for animations. */
  function applyMessage(model, msg) {
    const ev = msg.event;
    const r = room(model, ev.repo);
    for (const m of msg.repos || []) r.machines[m.machine] = m.last_seen;
    const before = r.jobs[ev.job_id] ? r.jobs[ev.job_id].stage : null;
    let job = null;
    if (msg.job) {
      job = normalizeJob(msg.job);
      r.jobs[ev.job_id] = job;
      recount(r);
    }
    model.seq = Math.max(model.seq, ev.seq || 0);
    return { event: ev, job, before, gate: gateResult(ev) };
  }

  /* 'pass' or 'fail' when an event is a gate verdict, else null. */
  function gateResult(ev) {
    if (ev.from === "gate" && ev.to === "review") return "pass";
    if (ev.from === "gate" && (ev.to === "build" || ev.to === "needs-human")) return "fail";
    if (ev.from === ev.to && /^final gate PASS/.test(ev.reason || "")) return "pass";
    if (ev.from === "final-review" && ev.to === "final-build" && /GATE/i.test(ev.reason || "")) return "fail";
    return null;
  }

  /* Where a job stands in the office and whether someone is working on it right now.
   * zone: reception | waiting | workshop | qa | review | elevator | outbox | boss | archive |
   *       trash | board (a spec that is still building: shown in the room header) */
  function placeFor(job) {
    const action = job.claim ? job.claim.action : null;
    const working = !!action;
    if (job.kind === "spec") {
      switch (job.stage) {
        case "building": return { zone: "board", working: false };
        case "final-review":
          if (action === "final-gate") return { zone: "qa", working: true };
          return { zone: "review", working: action === "final-review" };
        case "final-build": return { zone: "workshop", working };
        case "ready": return { zone: "outbox", working: false };
        case "needs-human": return { zone: "boss", working: false };
        case "done": return { zone: "archive", working: false };
        default: return { zone: "hall", working: false };
      }
    }
    switch (job.stage) {
      case "intake": return { zone: "reception", working };
      case "needs-info": return { zone: "waiting", working: false };
      case "build": return { zone: "workshop", working };
      case "gate": return { zone: "qa", working };
      case "review": return { zone: "review", working };
      case "merging": return { zone: "elevator", working };
      case "ready": return { zone: "outbox", working: false };
      case "needs-human": return { zone: "boss", working: false };
      case "done": return { zone: "archive", working: false };
      case "rejected": return { zone: "trash", working: false };
      default: return { zone: "hall", working: false };
    }
  }

  function isLive(job) {
    return FINISHED.indexOf(job.stage) < 0 && placeFor(job).zone !== "board";
  }

  function liveJobs(r) {
    return Object.values(r.jobs).filter(isLive).sort(byIssue);
  }

  function byIssue(a, b) {
    return (a.issue || 0) - (b.issue || 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  }

  /* Specs still building, with how many of their tickets are done. */
  function specs(r) {
    const all = Object.values(r.jobs);
    return all.filter(j => j.kind === "spec" && FINISHED.indexOf(j.stage) < 0).sort(byIssue).map(s => {
      const children = all.filter(j => j.spec === s.id && j.kind !== "spec");
      return { job: s, total: children.length, done: children.filter(c => c.stage === "done").length };
    });
  }

  function counts(model) {
    const out = { done: 0 };
    for (const r of Object.values(model.repos)) {
      out.done += r.done;
      for (const j of liveJobs(r)) out[j.stage] = (out[j.stage] || 0) + 1;
    }
    return out;
  }

  const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

  function links(job) {
    if (!REPO_RE.test(job.repo)) return { issue: null, pr: null };
    const base = "https://github.com/" + job.repo;
    return {
      issue: job.issue != null ? base + "/issues/" + job.issue : null,
      pr: job.pr ? base + "/pull/" + job.pr : null
    };
  }

  /* Incremental Server-Sent Events parser. Feed it text; it returns complete messages. */
  function parseSSE(buffer) {
    const messages = [];
    const text = buffer.replace(/\r\n/g, "\n");
    const blocks = text.split("\n\n");
    const rest = blocks.pop();
    for (const block of blocks) {
      let id = null; const data = [];
      for (const line of block.split("\n")) {
        if (!line || line[0] === ":") continue;
        const i = line.indexOf(":");
        const field = i < 0 ? line : line.slice(0, i);
        let value = i < 0 ? "" : line.slice(i + 1);
        if (value[0] === " ") value = value.slice(1);
        if (field === "id") id = value;
        else if (field === "data") data.push(value);
      }
      if (data.length) messages.push({ id, data: data.join("\n") });
    }
    return { messages, rest };
  }

  /* Hat and shirt palettes. Hats (model) stay >= 100 apart in RGB from every shirt (role). */
  const SHIRT_COLORS = { planner: "#5b8fd8", builder: "#e08a3c", reviewer: "#5fae6a", boss: "#c9506a" };
  const MODEL_COLORS = { haiku: "#e4f55a", sonnet: "#ff4fe0", opus: "#9a30f0" };
  const UNKNOWN_MODEL_COLOR = "#c8c8c8";
  const IDLE_COLOR = "#6f6987";

  /* The model an agent works on: the claim's model, else models[role], else null. */
  function hatModel(job, role) {
    if (job && job.claim && typeof job.claim.model === "string" && job.claim.model) return job.claim.model;
    const m = job && job.models ? job.models[role] : null;
    return m || null;
  }

  function hatColor(job, role) {
    if (!job) return IDLE_COLOR;
    const m = hatModel(job, role);
    return m && Object.prototype.hasOwnProperty.call(MODEL_COLORS, m) ? MODEL_COLORS[m] : UNKNOWN_MODEL_COLOR;
  }

  /* Room geometry. Seated agents sit SEATED_LIFT px higher so the shirt shows above the desk top. */
  const SEATS = { planner: { x: 37, y: 48 }, b0: { x: 82, y: 48 }, b1: { x: 124, y: 48 }, reviewer: { x: 219, y: 48 }, boss: { x: 300, y: 62 } };
  const DESK_TOP = { planner: 42, b0: 42, b1: 42, reviewer: 42 };
  const SPRITE_BODY = ["..hhh..", ".hhhhh.", ".sssss.", ".seses.", ".sssss.", "..bbb..", ".bbbbb.", "sbbdbbs", ".bbbbb."];
  const SPRITE_LEGS = [[".l...l.", ".k...k."], ["..l.l..", "..k.k.."]];
  const SEATED_LIFT = 3;

  function spriteTop(x, y, seated, bob) {
    return Math.round(y) - 11 - (seated ? SEATED_LIFT : 0) + bob;
  }

  return { SEATS, DESK_TOP, SPRITE_BODY, SPRITE_LEGS, SEATED_LIFT, spriteTop, STAGES, FINISHED, createModel, loadState, applyMessage, normalizeJob, gateResult,
    placeFor, isLive, liveJobs, specs, counts, links, parseSSE,
    SHIRT_COLORS, MODEL_COLORS, UNKNOWN_MODEL_COLOR, IDLE_COLOR, hatModel, hatColor };
});

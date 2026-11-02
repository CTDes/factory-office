/* node --test tests/js : the pure office model shared by every renderer. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const M = require("../../src/factory_office/web/model.js");

const FIXTURE = path.join(__dirname, "..", "fixtures", "events_v1.jsonl");

function row(over) {
  return Object.assign({ repo: "CTDes/textkit", job_id: "012-x", kind: "ticket", issue: 12, spec: null,
    stage: "build", ts: "2026-11-02T10:00:00+01:00", machine: "mac",
    job: { title: "Reading time", round: 1, risk: "low", pr: 7, claim: null, models: { builder: "sonnet" } } }, over);
}

test("placeFor: claim means an agent is working", () => {
  const waiting = M.normalizeJob(row());
  assert.deepEqual(M.placeFor(waiting), { zone: "workshop", working: false });
  const working = M.normalizeJob(row({ job: { claim: { action: "build", at: "x" } } }));
  assert.deepEqual(M.placeFor(working), { zone: "workshop", working: true });
});

test("placeFor: every ticket stage has a zone", () => {
  const zones = { intake: "reception", "needs-info": "waiting", build: "workshop", gate: "qa",
    review: "review", merging: "elevator", ready: "outbox", "needs-human": "boss", done: "archive",
    rejected: "trash", weird: "hall" };
  for (const [stage, zone] of Object.entries(zones)) {
    assert.equal(M.placeFor(M.normalizeJob(row({ stage }))).zone, zone, stage);
  }
});

test("placeFor: specs building go to the board, final gate to QA", () => {
  const spec = (stage, action) => M.normalizeJob(row({ kind: "spec", stage,
    job: { claim: action ? { action } : null } }));
  assert.equal(M.placeFor(spec("building")).zone, "board");
  assert.deepEqual(M.placeFor(spec("final-review", "final-gate")), { zone: "qa", working: true });
  assert.deepEqual(M.placeFor(spec("final-review", "final-review")), { zone: "review", working: true });
});

test("loadState counts finished jobs and keeps live ones", () => {
  const m = M.loadState(M.createModel(), {
    seq: 9,
    repos: [{ repo: "CTDes/textkit", machine: "mac", last_seen: "t" }],
    jobs: [row(), row({ job_id: "013-y", issue: 13, stage: "done" }), row({ job_id: "014-z", issue: 14, stage: "rejected" })]
  });
  const r = m.repos["CTDes/textkit"];
  assert.equal(m.seq, 9);
  assert.equal(r.done, 1);
  assert.equal(r.rejected, 1);
  assert.deepEqual(M.liveJobs(r).map(j => j.id), ["012-x"]);
  assert.deepEqual(M.counts(m), { done: 1, build: 1 });
});

test("applyMessage moves a job and reports gate verdicts", () => {
  const m = M.loadState(M.createModel(), { seq: 1, repos: [], jobs: [row({ stage: "gate" })] });
  const out = M.applyMessage(m, {
    event: { seq: 2, repo: "CTDes/textkit", job_id: "012-x", from: "gate", to: "review", reason: "GATE PASS round 1" },
    job: row({ stage: "review" }),
    repos: [{ repo: "CTDes/textkit", machine: "mac", last_seen: "t2" }]
  });
  assert.equal(out.before, "gate");
  assert.equal(out.gate, "pass");
  assert.equal(m.repos["CTDes/textkit"].jobs["012-x"].stage, "review");
  assert.equal(m.seq, 2);
  assert.equal(M.gateResult({ from: "gate", to: "build", reason: "GATE FAIL round 1" }), "fail");
  assert.equal(M.gateResult({ from: "intake", to: "build", reason: "ACCEPT" }), null);
});

test("a new repo appears with its first event", () => {
  const m = M.createModel();
  M.applyMessage(m, { event: { seq: 1, repo: "o/new", job_id: "001-a", from: "(new)", to: "intake", reason: "" },
    job: row({ repo: "o/new", job_id: "001-a", stage: "intake" }), repos: [{ repo: "o/new", machine: "m2", last_seen: "t" }] });
  assert.deepEqual(Object.keys(m.repos), ["o/new"]);
  assert.equal(m.repos["o/new"].machines.m2, "t");
});

test("specs report ticket progress", () => {
  const m = M.loadState(M.createModel(), { repos: [], jobs: [
    row({ job_id: "010-s", issue: 10, kind: "spec", stage: "building", job: { title: "Stats" } }),
    row({ job_id: "011-a", issue: 11, spec: "010-s", stage: "done" }),
    row({ job_id: "012-b", issue: 12, spec: "010-s", stage: "build" })
  ] });
  const [s] = M.specs(m.repos["CTDes/textkit"]);
  assert.equal(s.job.id, "010-s");
  assert.deepEqual([s.done, s.total], [1, 2]);
  assert.ok(!M.isLive(s.job));
});

test("links only for owner/name repos", () => {
  assert.deepEqual(M.links(M.normalizeJob(row())), {
    issue: "https://github.com/CTDes/textkit/issues/12", pr: "https://github.com/CTDes/textkit/pull/7" });
  assert.deepEqual(M.links(M.normalizeJob(row({ repo: "local-folder" }))), { issue: null, pr: null });
});

test("parseSSE handles split chunks, comments and multi-line data", () => {
  let out = M.parseSSE(": connected\n\nid: 3\ndata: {\"a\"");
  assert.deepEqual(out.messages, []);
  out = M.parseSSE(out.rest + ":1}\n\n: ping\n\nid: 4\r\ndata: x\r\ndata: y\r\n\r\npartial");
  assert.deepEqual(out.messages, [{ id: "3", data: "{\"a\":1}" }, { id: "4", data: "x\ny" }]);
  assert.equal(out.rest, "partial");
});

test("real factory events normalize", () => {
  const events = fs.readFileSync(FIXTURE, "utf8").trim().split("\n").map(l => JSON.parse(l));
  const last = events.filter(e => e.job).pop();
  const job = M.normalizeJob({ repo: last.repo, job_id: last.job_id, kind: last.kind, issue: last.issue,
    spec: last.spec, stage: last.to, ts: last.ts, machine: last.machine, job: last.job });
  assert.equal(job.title, last.job.title);
  assert.equal(job.pr, last.job.pr);
  assert.equal(M.placeFor(job).zone, M.placeFor({ kind: "ticket", stage: last.to, claim: null }).zone);
});

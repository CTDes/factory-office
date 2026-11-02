/* node --test tests/js : which model a hat shows, and its colour. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const M = require("../../src/factory_office/web/model.js");

const WEB = path.join(__dirname, "..", "..", "src", "factory_office", "web");
const job = (claim, models) => ({ claim, models });
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const dist = (a, b) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i]));
const SHIRTS = () => Object.values(M.SHIRT_COLORS);
const MODELS = () => Object.values(M.MODEL_COLORS);

test("hat_model_claim_model_wins", () => {
  assert.equal(M.hatModel(job({ action: "build", model: "opus" }, { builder: "sonnet" }), "builder"), "opus");
});

test("hat_model_falls_back_to_models_role", () => {
  assert.equal(M.hatModel(job(null, { builder: "sonnet" }), "builder"), "sonnet");
  assert.equal(M.hatModel(job({ action: "build" }, { builder: "sonnet" }), "builder"), "sonnet");
  assert.equal(M.hatModel(job({ action: "build", model: "" }, { builder: "sonnet" }), "builder"), "sonnet");
});

test("hat_model_unknown_is_null_and_claims_cover_missing_roles", () => {
  assert.equal(M.hatModel(job(null, { builder: "sonnet" }), "planner"), null);
  assert.equal(M.hatModel(job(null, undefined), "planner"), null);
  assert.equal(M.hatModel(job({ action: "plan", model: "opus" }, { builder: "a", reviewer: "b" }), "planner"), "opus");
  assert.equal(M.hatModel(job({ action: "final-review", model: "sonnet" }, {}), "reviewer"), "sonnet");
});

test("hat_color_model_neutral_and_idle", () => {
  for (const m of ["haiku", "sonnet", "opus"]) {
    assert.equal(M.hatColor(job({ model: m }, {}), "builder"), M.MODEL_COLORS[m]);
  }
  assert.equal(M.hatColor(job(null, {}), "builder"), M.UNKNOWN_MODEL_COLOR);
  assert.equal(M.hatColor(job({ model: "gpt" }, {}), "builder"), M.UNKNOWN_MODEL_COLOR);
  assert.equal(M.hatColor(null, "builder"), M.IDLE_COLOR);
  for (const j of [job(null, {}), job({ model: "gpt" }, {}), job({ model: "opus" }, {})]) {
    assert.ok(!SHIRTS().includes(M.hatColor(j, "builder")));
  }
});

test("palette_neutral_is_distinct", () => {
  for (const c of [...SHIRTS(), ...MODELS()]) assert.notEqual(M.UNKNOWN_MODEL_COLOR, c);
});

test("palette_hats_100_rgb_apart", () => {
  for (const h of [...MODELS(), M.UNKNOWN_MODEL_COLOR]) {
    for (const s of SHIRTS()) assert.ok(dist(h, s) >= 100, `${h} vs ${s}`);
  }
  const ms = MODELS();
  for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++) assert.ok(dist(ms[i], ms[j]) >= 100);
});

test("legend_swatches_match_palette", () => {
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(WEB, "office.css"), "utf8");
  const want = { planner: M.SHIRT_COLORS.planner, builder: M.SHIRT_COLORS.builder, reviewer: M.SHIRT_COLORS.reviewer,
    haiku: M.MODEL_COLORS.haiku, sonnet: M.MODEL_COLORS.sonnet, opus: M.MODEL_COLORS.opus, unknown: M.UNKNOWN_MODEL_COLOR };
  for (const [name, color] of Object.entries(want)) {
    assert.match(html, new RegExp(`class="sw ${name}"`), name);
    const m = css.match(new RegExp(`\\.sw\\.${name}\\s*\\{\\s*background:\\s*(#[0-9a-fA-F]{6})`));
    assert.ok(m, `css for ${name}`);
    assert.equal(m[1].toLowerCase(), color.toLowerCase());
  }
});

test("office_js_uses_model_hat_color", () => {
  const src = fs.readFileSync(path.join(WEB, "office.js"), "utf8");
  assert.ok(!src.includes("models[a.role]"));
  assert.ok(!/const (ROLE|MODEL)\b/.test(src));
  assert.ok(src.includes("M.hatColor"));
});

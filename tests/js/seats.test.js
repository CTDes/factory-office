/* node --test tests/js : seated agents show their shirt colour above the desk. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const M = require("../../src/factory_office/web/model.js");

const WEB = path.join(__dirname, "..", "..", "src", "factory_office", "web");
const DESKS = ["planner", "b0", "b1", "reviewer"];
const rows = () => M.SPRITE_BODY.concat(M.SPRITE_LEGS[0]);
const above = (seat, bob, pred) => {
  const top = M.spriteTop(M.SEATS[seat].x, M.SEATS[seat].y, true, bob);
  const deskY = M.DESK_TOP[seat];
  return rows().filter((row, r) => pred(row) && top + r < deskY).length;
};
const isShirt = row => row.includes("b");
const isLeg = row => /[lk]/.test(row);

test("seats_shirt_shows_at_least_two_rows_above_desk", () => {
  for (const s of DESKS) for (const bob of [0, 1]) assert.ok(above(s, bob, isShirt) >= 2, `${s} bob ${bob}`);
});

test("seats_at_most_three_shirt_rows_and_no_legs_above_desk", () => {
  for (const s of DESKS) for (const bob of [0, 1]) {
    assert.ok(above(s, bob, isShirt) <= 3, `${s} bob ${bob}`);
    assert.equal(above(s, bob, isLeg), 0, `${s} bob ${bob} legs`);
  }
});

test("seats_walking_sprite_top_and_rows_unchanged", () => {
  assert.equal(M.spriteTop(50, 40.6, false, 1), 41 - 11 + 1);
  assert.equal(M.spriteTop(50, 20, false, 0), 9);
  assert.deepEqual(M.SPRITE_BODY, ["..hhh..", ".hhhhh.", ".sssss.", ".seses.", ".sssss.", "..bbb..", ".bbbbb.", "sbbdbbs", ".bbbbb."]);
  assert.deepEqual(M.SPRITE_LEGS, [[".l...l.", ".k...k."], ["..l.l..", "..k.k.."]]);
});

test("seats_room_geometry_unchanged", () => {
  assert.deepEqual(DESKS.map(s => M.SEATS[s].x), [37, 82, 124, 219]);
  assert.deepEqual(DESKS.map(s => M.DESK_TOP[s]), [42, 42, 42, 42]);
  assert.deepEqual(M.SEATS.boss, { x: 300, y: 62 });
});

test("seats_office_js_uses_model_geometry", () => {
  const src = fs.readFileSync(path.join(WEB, "office.js"), "utf8");
  assert.ok(!/const\s+BODY\b/.test(src));
  assert.ok(!/const\s+LEGS\b/.test(src));
  assert.ok(!/const\s+SEATS\b/.test(src));
  assert.match(src, /M\.SEATS/);
  assert.match(src, /M\.spriteTop/);
  assert.match(src, /M\.hatColor/);
});

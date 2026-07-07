"use strict";
// D-4: JS unit tests for the debounce helper exported by app.js.
// Uses Node's built-in mock timers for deterministic, instant runs.
const test = require("node:test");
const assert = require("node:assert/strict");

const { debounce } = require("../../src/ameli_app/static/js/app.js");

test("debounce: collapses a rapid burst into a single trailing call", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  let lastArg;
  const fn = debounce((x) => {
    calls += 1;
    lastArg = x;
  }, 100);

  fn("a");
  fn("b");
  fn("c");
  assert.equal(calls, 0, "must not fire before the delay elapses");

  t.mock.timers.tick(99);
  assert.equal(calls, 0, "must not fire one tick early");

  t.mock.timers.tick(1);
  assert.equal(calls, 1, "fires exactly once after the delay");
  assert.equal(lastArg, "c", "with the arguments of the last call");
});

test("debounce: an interrupted timer never fires the stale call", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const fn = debounce(() => {
    calls += 1;
  }, 50);

  fn();
  t.mock.timers.tick(40); // not yet
  fn(); // resets the timer
  t.mock.timers.tick(40); // 40 < 50 since the reset -> still nothing
  assert.equal(calls, 0);
  t.mock.timers.tick(10); // now 50 since the reset
  assert.equal(calls, 1);
});

test("debounce: separate settled bursts each fire once", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const fn = debounce(() => {
    calls += 1;
  }, 50);

  fn();
  t.mock.timers.tick(50);
  fn();
  t.mock.timers.tick(50);
  assert.equal(calls, 2);
});

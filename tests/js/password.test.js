"use strict";
// D-4: JS unit tests for the password helpers exported by app.js.
// Runner: Node's built-in test module (`node --test tests/js/`), zero deps.
// app.js guards its DOM bootstrap on `typeof document`, so requiring it
// here loads only the pure functions + the CommonJS export surface.
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  generatePassword,
  evaluatePasswordStrength,
  PASSWORD_SYMBOLS,
} = require("../../src/ameli_app/static/js/app.js");

// ---------------------------------------------------------------------------
// generatePassword
// ---------------------------------------------------------------------------

test("generatePassword: default length is 18", () => {
  assert.equal(generatePassword().length, 18);
});

test("generatePassword: honours a custom length", () => {
  assert.equal(generatePassword(24).length, 24);
  assert.equal(generatePassword(12).length, 12);
});

test("generatePassword: always satisfies the server policy classes", () => {
  // The Django validator requires >=1 upper, lower, digit and a symbol
  // from the allowed set. Run many samples so a rare miss surfaces.
  for (let i = 0; i < 200; i += 1) {
    const pw = generatePassword();
    assert.match(pw, /[A-Z]/, `missing uppercase in ${pw}`);
    assert.match(pw, /[a-z]/, `missing lowercase in ${pw}`);
    assert.match(pw, /[0-9]/, `missing digit in ${pw}`);
    assert.ok(
      [...pw].some((ch) => PASSWORD_SYMBOLS.includes(ch)),
      `missing allowed symbol in ${pw}`,
    );
  }
});

test("generatePassword: only uses characters from the allowed alphabet", () => {
  // Guards against ambiguous chars (0/O, 1/l/I) leaking in — the generator
  // deliberately drops them.
  const allowed = new Set([
    ..."ABCDEFGHJKLMNPQRSTUVWXYZ",
    ..."abcdefghijkmnopqrstuvwxyz",
    ..."23456789",
    ...PASSWORD_SYMBOLS,
  ]);
  const pw = generatePassword(64);
  for (const ch of pw) assert.ok(allowed.has(ch), `unexpected char ${ch}`);
});

test("generatePassword: successive calls differ (uses real entropy)", () => {
  const seen = new Set();
  for (let i = 0; i < 20; i += 1) seen.add(generatePassword());
  assert.equal(seen.size, 20, "20 draws should all be distinct");
});

// ---------------------------------------------------------------------------
// evaluatePasswordStrength
// ---------------------------------------------------------------------------

test("evaluatePasswordStrength: empty string is weak", () => {
  const s = evaluatePasswordStrength("");
  assert.equal(s.level, "weak");
  assert.equal(s.percent, 24);
});

test("evaluatePasswordStrength: single-class short string is weak", () => {
  // "abcdefgh": lower only (score 1) -> weak.
  assert.equal(evaluatePasswordStrength("abcdefgh").level, "weak");
});

test("evaluatePasswordStrength: 12+ chars missing classes is medium", () => {
  // length + lower + digit = 3 checks -> medium (score <= 4).
  const s = evaluatePasswordStrength("abcdefghij12");
  assert.equal(s.level, "medium");
  assert.equal(s.percent, 62);
});

test("evaluatePasswordStrength: full policy is strong", () => {
  const s = evaluatePasswordStrength("Abcdefghij1!");
  assert.equal(s.level, "strong");
  assert.equal(s.percent, 100);
  assert.deepEqual(s.checks, {
    length: true,
    upper: true,
    lower: true,
    digit: true,
    symbol: true,
  });
});

test("evaluatePasswordStrength: a freshly generated password is strong", () => {
  // Ties the two helpers together: the generator's output must clear the
  // strength bar it feeds.
  assert.equal(evaluatePasswordStrength(generatePassword()).level, "strong");
});

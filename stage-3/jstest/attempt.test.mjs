import { test } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { createAttemptTracker } from '../web/js/attempt.js';

const counter = () => {
  let n = 0;
  return () => `k${++n}`;
};

test('same scope and fingerprint keeps the key; a change mints a new one', () => {
  const t = createAttemptTracker(counter());
  const a = t.attemptFor('pay', 'bob|1500|');
  assert.deepEqual(t.attemptFor('pay', 'bob|1500|'), a);
  const b = t.attemptFor('pay', 'bob|1600|');
  assert.notEqual(b.key, a.key);
  assert.deepEqual(t.attemptFor('pay', 'bob|1600|'), b);
  assert.notEqual(t.attemptFor('pay', 'bob|1500|').key, a.key);
});

test('scopes are independent and forget starts over', () => {
  const t = createAttemptTracker(counter());
  const pay = t.attemptFor('pay', 'x');
  const auth = t.attemptFor('authorize', 'x');
  assert.notEqual(pay.key, auth.key);
  assert.deepEqual(t.attemptFor('pay', 'x'), pay);
  t.forget('pay');
  assert.notEqual(t.attemptFor('pay', 'x').key, pay.key);
  assert.deepEqual(t.attemptFor('authorize', 'x'), auth);
});

test('default key generator works with and without crypto.randomUUID', () => {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const real = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  const stub = (c) => Object.defineProperty(globalThis, 'crypto', { value: c, configurable: true });
  try {
    const k = createAttemptTracker().attemptFor('s', 'f').key;
    assert.ok(k.length >= 1 && k.length <= 255);
    stub({ getRandomValues: (b) => webcrypto.getRandomValues(b) }); // insecure context: no randomUUID
    const fallback = createAttemptTracker();
    const seen = new Set();
    for (let i = 0; i < 50; i++) {
      const key = fallback.attemptFor(`s${i}`, 'f').key;
      assert.match(key, uuid);
      seen.add(key);
    }
    assert.equal(seen.size, 50);
    stub(undefined);
    assert.match(createAttemptTracker().attemptFor('s', 'f').key, uuid);
  } finally {
    Object.defineProperty(globalThis, 'crypto', real);
  }
});

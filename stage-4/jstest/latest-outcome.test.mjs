import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLatestWins } from '../web/js/latest.js';
import { classify } from '../web/js/outcome.js';

test('only the most recently begun token is current', () => {
  const l = createLatestWins();
  const first = l.begin();
  assert.equal(l.isCurrent(first), true);
  const second = l.begin();
  assert.equal(l.isCurrent(first), false);
  assert.equal(l.isCurrent(second), true);
  assert.equal(l.isCurrent(0), false);
});

test('out-of-order responses: the later refresh wins', async () => {
  const l = createLatestWins();
  let shown = null;
  const read = (value, ms) => {
    const token = l.begin();
    return new Promise((r) => setTimeout(r, ms)).then(() => {
      if (l.isCurrent(token)) shown = value;
    });
  };
  await Promise.all([read('old', 30), read('new', 5)]);
  assert.equal(shown, 'new');
});

test('classify', () => {
  const cases = [
    [{ networkError: new Error('x') }, 'uncertain'],
    [{ networkError: true, status: 200, json: {} }, 'uncertain'],
    [{}, 'uncertain'],
    [{ status: 200, json: { a: 1 } }, 'success'],
    [{ status: 201, json: { a: 1 } }, 'success'],
    [{ status: 200, json: undefined }, 'uncertain'],
    [{ status: 200, json: null }, 'uncertain'],
    [{ status: 204 }, 'success'],
    [{ status: 401, json: { error: { code: 'unauthenticated' } } }, 'unauthenticated'],
    [{ status: 401 }, 'unauthenticated'],
    [{ status: 409, json: { error: { code: 'insufficient_funds' } } }, 'refused'],
    [{ status: 422, json: {} }, 'refused'],
    [{ status: 404 }, 'refused'],
    [{ status: 429 }, 'refused'],
    [{ status: 500, json: { error: {} } }, 'uncertain'],
    [{ status: 502 }, 'uncertain'],
    [{ status: 503, json: {} }, 'uncertain'],
    [{ status: 302 }, 'uncertain'],
  ];
  for (const [input, want] of cases) assert.equal(classify(input), want, JSON.stringify(input));
});

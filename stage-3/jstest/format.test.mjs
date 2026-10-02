import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatTime, timeEl } from '../web/js/format.js';

// Stage 3 stamps API-created payments with microseconds; the feed must read them like any other instant.
test('formatTime reads microsecond instants at minute resolution', () => {
  for (const [micro, whole] of [
    ['2026-09-24T13:20:00.123456+00:00', '2026-09-24T13:20:00+00:00'],
    ['2026-09-24T13:20:59.999999+00:00', '2026-09-24T13:20:59+00:00'],
    ['2026-09-24T13:20:00.000001+00:00', '2026-09-24T13:20:00+00:00'],
    ['2026-09-24T15:20:00.654321+02:00', '2026-09-24T15:20:00+02:00'],
  ]) {
    assert.equal(formatTime(micro), formatTime(whole), micro);
    assert.match(formatTime(micro), /^[A-Z][a-z]{2} \d{1,2}, \d{2}:\d{2}$/, micro);
  }
});

test('formatTime shows an unparseable value as given', () => {
  assert.equal(formatTime('not a time'), 'not a time');
});

test('timeEl keeps the exact instant for assistive tech and tooltips', () => {
  const calls = [];
  const h = (tag, attrs) => (calls.push({ tag, attrs }), { tag, attrs });
  timeEl(h, '2026-09-24T13:20:00.123456+00:00');
  assert.equal(calls[0].tag, 'time');
  assert.equal(calls[0].attrs.datetime, '2026-09-24T13:20:00.123456+00:00');
  assert.equal(calls[0].attrs['aria-label'], '2026-09-24T13:20:00.123456+00:00');
});

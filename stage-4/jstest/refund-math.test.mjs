import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canRefund, currentAmount, refundSums, remainder } from '../web/js/refund-math.js';

test('refundSums totals refunds per target and ignores other payments', () => {
  const sums = refundSums([
    { payment_id: 'p_3', amount: 200, refund_of: 'p_1' },
    { payment_id: 'p_2', amount: 900, refund_of: null },
    { payment_id: 'p_4', amount: 300, refund_of: 'p_1' },
    { payment_id: 'p_5', amount: 50, refund_of: 'p_2' },
  ]);
  assert.equal(sums.get('p_1'), 500);
  assert.equal(sums.get('p_2'), 50);
  assert.equal(sums.has('p_3'), false);
});

test('refundSums keeps adding into an existing map (older pages)', () => {
  const sums = refundSums([{ amount: 100, refund_of: 'p_1' }]);
  refundSums([{ amount: 25, refund_of: 'p_1' }], sums);
  assert.equal(sums.get('p_1'), 125);
});

test('currentAmount is the highest revision, null without a usable one', () => {
  assert.equal(currentAmount([{ revision: 1, amount: 1000 }, { revision: 3, amount: 400 }, { revision: 2, amount: 700 }]), 400);
  assert.equal(currentAmount([]), null);
  assert.equal(currentAmount(undefined), null);
  assert.equal(currentAmount([{ revision: '1', amount: 5 }, { revision: 2 }]), null);
});

test('remainder uses the read corrected amount over the original and never goes negative', () => {
  assert.equal(remainder(1000, null, 300), 700);
  assert.equal(remainder(1000, 400, 300), 100);
  assert.equal(remainder(1000, 0, 300), 0);
  assert.equal(remainder(1000, 250, 300), 0);
});

test('only the receiver of a non-refund payment may be offered a refund', () => {
  const me = { user_id: 'u_bob' };
  assert.equal(canRefund({ to_user_id: 'u_bob', refund_of: null }, me), true);
  assert.equal(canRefund({ to_user_id: 'u_bob', refund_of: 'p_1' }, me), false);
  assert.equal(canRefund({ to_user_id: 'u_ada', refund_of: null }, me), false);
});

// What the page can say about refunds from data it already holds: the feed shows each
// payment at its original amount, so a corrected amount is learned only from the revisions read.

// refundSums maps a target payment id to the total of the refunds of it present in `payments`.
export function refundSums(payments, into = new Map()) {
  for (const p of payments) {
    if (p.refund_of) into.set(p.refund_of, (into.get(p.refund_of) || 0) + p.amount);
  }
  return into;
}

// currentAmount is the amount of the highest revision, or null when no usable revision was read.
export function currentAmount(revisions) {
  let best = null;
  for (const r of revisions || []) {
    if (Number.isInteger(r?.revision) && Number.isInteger(r?.amount) && (best === null || r.revision > best.revision)) best = r;
  }
  return best === null ? null : best.amount;
}

// remainder never goes below zero; `current` (a read corrected amount) wins over the original.
export function remainder(original, current, refunded) {
  return Math.max(0, (current ?? original) - refunded);
}

export const canRefund = (p, me) => p.to_user_id === me.user_id && !p.refund_of;

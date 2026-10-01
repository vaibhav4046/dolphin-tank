// Exact money helpers. Amounts are integers in minor units; BigInt internally, never floats.
const MAX_MINOR = 1000000000n;

export function parseAmount(text, minorUnits) {
  const s = String(text ?? '').trim();
  if (s === '') return { ok: false, reason: 'empty' };
  const m = /^(\d+)(?:\.(\d+))?$/.exec(s);
  if (!m) return { ok: false, reason: 'format' };
  const frac = m[2] ?? '';
  if (frac.length > minorUnits) return { ok: false, reason: 'precision' };
  const minor = BigInt(m[1] + frac.padEnd(minorUnits, '0'));
  if (minor < 1n || minor > MAX_MINOR) return { ok: false, reason: 'range' };
  return { ok: true, minor: Number(minor) };
}

// formatDecimal(1550, 2) -> '15.50'; no decimal point when minorUnits is 0.
export function formatDecimal(minor, minorUnits) {
  let v = BigInt(minor);
  const sign = v < 0n ? '-' : '';
  if (v < 0n) v = -v;
  if (minorUnits === 0) return sign + v.toString();
  const digits = v.toString().padStart(minorUnits + 1, '0');
  const cut = digits.length - minorUnits;
  return `${sign}${digits.slice(0, cut)}.${digits.slice(cut)}`;
}

export function formatAmount(minor, minorUnits, currency) {
  return `${formatDecimal(minor, minorUnits)} ${currency}`;
}

// Whole-unit shares; the remainder goes one unit each to the first participants (stage-1 §9).
export function splitShares(amountMinor, n) {
  if (!Number.isInteger(n) || n <= 0) return [];
  const total = BigInt(amountMinor);
  const count = BigInt(n);
  const base = total / count;
  const rem = Number(total % count);
  return Array.from({ length: n }, (_, i) => Number(base) + (i < rem ? 1 : 0));
}

export function parseHandles(text) {
  return String(text ?? '')
    .split(',')
    .map((h) => h.trim())
    .filter((h) => h !== '');
}

import { formatAmount } from "./money.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n) => String(n).padStart(2, "0");

// 'Sep 24, 11:04' in the viewer's local time; unparseable input is shown as given.
export function formatTime(rfc3339) {
  const d = new Date(rfc3339);
  if (Number.isNaN(d.getTime())) return String(rfc3339);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const money = (minor, me) => formatAmount(minor, me.minor_units, me.currency);
export const at = (handle) => `@${handle}`;

export function timeEl(h, rfc3339) {
  return h("time", { datetime: rfc3339, title: rfc3339, "aria-label": rfc3339, text: formatTime(rfc3339) });
}

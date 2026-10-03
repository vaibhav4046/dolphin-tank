import * as api from "./api.js";
import { createAttemptTracker } from "./attempt.js";
import { parseAmount } from "./money.js";
import { classify } from "./outcome.js";
import { amountText, refusalText, uncertainText } from "./messages.js";

const tracker = createAttemptTracker();

// readAmount parses the decimal field; on failure it shows the form's error and returns null.
export function readAmount(text, me, feedback) {
  const parsed = parseAmount(text, me.minor_units);
  if (parsed.ok) return Number(parsed.minor);
  feedback.showError(amountText(parsed.reason, me.minor_units), "Check the amount");
  return null;
}

export const trimmed = (text) => text.trim();

// busy guards a button against re-entry while its write is in flight, without
// disabling it (a disabled control drops keyboard focus).
export async function busy(button, fn) {
  if (button.getAttribute("aria-busy") === "true") return undefined;
  button.setAttribute("aria-busy", "true");
  try {
    return await fn();
  } finally {
    button.removeAttribute("aria-busy");
  }
}

// runWrite is the single write path of the product. Idempotent writes take their key from
// the attempt tracker, so an unchanged form re-sends the same key and body however the last
// attempt ended; any changed field mints a new key.
//   scope/fingerprint  attempt identity (fingerprint = raw field values)
//   what               noun for the uncertain message ("payment")
//   onSuccess(json)    runs after the notices are cleared; refresh goes here (not awaited, so the button frees up
//                      even if a refresh read is slow)
//   onRefused(res)     runs after the refusal is shown; refresh goes here
export async function runWrite({ method = "POST", path, body, scope, fingerprint, what, feedback, onSuccess, onRefused, onUncertain, refusal = refusalText }) {
  feedback.clear();
  const key = scope ? tracker.attemptFor(scope, JSON.stringify(fingerprint)).key : undefined;
  const res = await api.request(method, path, { body, key });
  const kind = classify(res);
  if (kind === "success") {
    feedback.clear();
    onSuccess?.(res.json);
  } else if (kind === "refused") {
    feedback.showError(refusal(res.json));
    onRefused?.(res);
  } else if (kind === "uncertain") {
    feedback.showUncertain(uncertainText(what));
    onUncertain?.(res);
  }
  return kind;
}

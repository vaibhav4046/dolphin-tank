const REFUSAL_TEXT = {
  insufficient_funds: "Not enough available funds. Money on hold cannot be spent.",
  not_found: "No one has that handle.",
  self_payment: "You cannot send this to yourself.",
  self_request: "You cannot send this to yourself.",
  validation_failed: "Check the amount, note and visibility.",
  request_not_pending: "This request is no longer pending.",
  authorization_not_open: "This authorisation is already closed.",
  authorization_expired: "This authorisation has expired.",
  capture_exceeds_authorization: "That is more than the amount still on hold.",
  forbidden: "You cannot do that.",
  handle_taken: "That handle is already taken. Try a different email address.",
  email_taken: "An account with that email already exists. Try logging in.",
  unauthenticated: "Email or password is not right.",
  malformed_request: "Something in that request was not readable. Check the details and try again.",
  idempotency_key_reuse: "That request was already sent with different details. Change a field and try again.",
};

// refusalText maps an error envelope to plain language; unknown codes fall back to the server message.
export function refusalText(json) {
  const code = json?.error?.code;
  return REFUSAL_TEXT[code] || json?.error?.message || "That did not go through. Please try again.";
}

export const AMOUNT_TEXT = {
  empty: "Enter an amount.",
  format: "Use digits and one decimal point, for example 15.00.",
  range: "That amount is outside the allowed range. Enter more than zero and no more than 1,000,000,000 smallest units.",
};

export function amountText(reason, minorUnits) {
  if (reason === "precision") {
    return minorUnits === 0 ? "This currency has no decimal places." : `This currency allows at most ${minorUnits} decimal places.`;
  }
  return AMOUNT_TEXT[reason] || AMOUNT_TEXT.format;
}

export const uncertainText = (what) =>
  `We could not confirm this ${what}. Nothing is lost: retry sends the same ${what} once.`;

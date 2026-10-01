import { chip } from "./dom.js";

// Status is carried by glyph shape, label and opacity, never by colour alone.
const REQUEST = {
  pending: ["ring", "Pending"],
  paid: ["disc", "Paid"],
  declined: ["cross", "Declined", "quiet"],
  cancelled: ["slash", "Cancelled", "quiet"],
};

const AUTHORIZATION = {
  open: ["ring", "On hold"],
  captured: ["disc", "Captured"],
  voided: ["cross", "Voided", "quiet"],
  expired: ["dash", "Expired", "quiet"],
};

const build = (table, status) => {
  const [glyphKind, label, tone] = table[status] || ["dash", status];
  return chip(glyphKind, label, tone);
};

export const requestChip = (status) => build(REQUEST, status);
export const authorizationChip = (status) => build(AUTHORIZATION, status);
export const isQuiet = (status) => ["declined", "cancelled", "voided", "expired"].includes(status);

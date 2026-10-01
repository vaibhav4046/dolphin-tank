import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { at, money } from "./format.js";
import { busy, readAmount, runWrite, trimmed } from "./writes.js";

const field = (id, label, input) => h("div", { class: "field" }, h("label", { for: id, text: label }), input);

export function createRequestForm({ getMe, onDone }) {
  const handle = h("input", { id: "request-handle", testid: "request-handle", type: "text", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "ada" });
  const amount = h("input", { id: "request-amount", testid: "request-amount", type: "text", inputmode: "decimal", autocomplete: "off", placeholder: "12.00" });
  const note = h("input", { id: "request-note", testid: "request-note", type: "text", autocomplete: "off", maxlength: "200" });
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: "request-error", uncertain: "request-uncertain", success: "request-success" });
  const submit = h("button", { type: "submit", testid: "request-submit", text: "Request money", data: { variant: "secondary" } });

  const form = h("form", { class: "card", novalidate: true, "aria-labelledby": "request-title" },
    h("h2", { id: "request-title", text: "Request money" }),
    h("p", { class: "hint", text: "Ask someone to pay you. Nothing moves until they pay." }),
    field("request-handle", "Ask this handle", handle),
    field("request-amount", "Amount", amount),
    field("request-note", "Note (optional)", note),
    notices,
    h("div", { class: "form-actions" }, submit));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return busy(submit, async () => {
      const me = getMe();
      const raw = { handle: handle.value, amount: amount.value, note: note.value };
      feedback.clear();
      const minor = readAmount(raw.amount, me, feedback);
      if (minor === null) return;
      const payer = trimmed(raw.handle);
      if (!payer) return feedback.showError("Enter the handle of the person you are asking.", "Check the handle");
      await runWrite({
        path: "/requests", scope: "request", fingerprint: raw, what: "request", feedback,
        body: { payer_handle: payer, amount: minor, note: raw.note },
        onSuccess: async () => { feedback.showSuccess(`Asked ${at(payer)} for ${money(minor, me)}.`); await onDone(); },
        onRefused: () => onDone(),
      });
    });
  });

  return { el: form };
}

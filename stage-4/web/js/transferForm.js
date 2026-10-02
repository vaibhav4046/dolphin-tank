import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { money, at } from "./format.js";
import { busy, readAmount, runWrite, trimmed } from "./writes.js";

function field(id, label, input) {
  return h("div", { class: "field" }, h("label", { for: id, text: label }), input);
}

// createTransferForm builds the pay and authorise cards, which share every input rule.
// prefix is the testid prefix ("pay" | "authorize"); the write goes to path with scope = prefix.
export function createTransferForm({ prefix, title, intro, submitLabel, path, what, variant, success, getMe, onDone }) {
  const id = (n) => `${prefix}-${n}`;
  const handle = h("input", { id: id("handle"), testid: id("handle"), type: "text", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "bob" });
  const amount = h("input", { id: id("amount"), testid: id("amount"), type: "text", inputmode: "decimal", autocomplete: "off", placeholder: "15.00" });
  const note = h("input", { id: id("note"), testid: id("note"), type: "text", autocomplete: "off", maxlength: "200" });
  const visibility = h("select", { id: id("visibility"), testid: id("visibility") },
    h("option", { value: "public", text: "Public" }), h("option", { value: "private", text: "Private" }));
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: id("error"), uncertain: id("uncertain"), success: id("success") });
  const submit = h("button", { type: "submit", testid: id("submit"), text: submitLabel, data: { variant } });
  submit.setAttribute("data-variant", variant);

  const form = h("form", { class: "card", novalidate: true, "aria-labelledby": id("title") },
    h("h2", { id: id("title"), text: title }),
    h("p", { class: "hint", text: intro }),
    field(id("handle"), "Recipient handle", handle),
    h("div", { class: "field-row two" }, field(id("amount"), "Amount", amount), field(id("visibility"), "Visibility", visibility)),
    field(id("note"), "Note (optional)", note),
    notices,
    h("div", { class: "form-actions" }, submit));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return busy(submit, async () => {
      const me = getMe();
      const raw = { handle: handle.value, amount: amount.value, note: note.value, visibility: visibility.value };
      feedback.clear();
      const minor = readAmount(raw.amount, me, feedback);
      if (minor === null) return;
      const to = trimmed(raw.handle);
      if (!to) return feedback.showError("Enter the handle of the person you are sending to.", "Check the recipient");
      await runWrite({
        path, scope: prefix, fingerprint: raw, what, feedback,
        body: { to_handle: to, amount: minor, note: raw.note, visibility: raw.visibility },
        onSuccess: async () => { feedback.showSuccess(success(money(minor, me), at(to))); await onDone(); },
        onRefused: () => onDone(),
      });
    });
  });

  return { el: form };
}

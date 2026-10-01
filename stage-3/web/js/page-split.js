import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { at, money } from "./format.js";
import { formatAmount, parseAmount, parseHandles, splitShares } from "./money.js";
import { amountText } from "./messages.js";
import { createRefresher } from "./refresh.js";
import { busy, readAmount, runWrite } from "./writes.js";
import { createWalletStrip } from "./wallet.js";

export function mountSplitPage(shell) {
  let me = null;
  let layout = [];
  const strip = createWalletStrip();
  const amount = h("input", { id: "split-amount", testid: "split-amount", type: "text", inputmode: "decimal", autocomplete: "off", placeholder: "30.00" });
  const handles = h("input", { id: "split-handles", testid: "split-handles", type: "text", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "ada, bob, cy" });
  const note = h("input", { id: "split-note", testid: "split-note", type: "text", autocomplete: "off", maxlength: "200" });
  const preview = h("div", { class: "preview", testid: "split-preview", "aria-live": "polite" });
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: "split-error", uncertain: "split-uncertain", success: "split-success" });
  const created = h("div", { class: "stack" });
  const submit = h("button", { type: "submit", testid: "split-submit", text: "Send requests", data: { variant: "primary" } });

  const refresh = createRefresher({ me: "/me" },
    ({ me: next }) => {
      me = next;
      if (!strip.el.isConnected) shell.main.replaceChildren(...layout);
      shell.showSignedIn(me);
      strip.update(me);
      renderPreview();
      shell.setBusy(false);
    },
    () => (me ? strip.showRefreshFailed() : shell.main.replaceChildren(h("div", { class: "empty", role: "alert" },
      h("strong", { text: "We could not load this page" }), h("button", { type: "button", text: "Try again", onclick: () => location.reload() })))),
  );

  // The preview uses the same splitShares rule the service applies, in the order the handles are typed.
  function computeShares() {
    const names = parseHandles(handles.value);
    if (names.length === 0) return { hint: "Add at least one handle, separated by commas, to see each share." };
    if (new Set(names).size !== names.length) return { hint: "List each person once." };
    if (amount.value.trim() === "") return { hint: "Enter an amount to see each share." };
    const parsed = parseAmount(amount.value, me.minor_units);
    if (!parsed.ok) return { hint: amountText(parsed.reason, me.minor_units) };
    return { names, shares: splitShares(Number(parsed.minor), names.length) };
  }

  function renderPreview() {
    if (!me) return;
    const { hint, names, shares } = computeShares();
    if (hint) {
      preview.replaceChildren(h("p", { class: "hint", text: hint }));
      return;
    }
    preview.replaceChildren(
      h("p", { class: "hint", text: "Each person's share, in the order typed. Extra units go to the first names." }),
      h("ul", {}, names.map((name, i) => h("li", {},
        h("span", { text: at(name) }),
        h("span", { class: "num", testid: `split-share-${name}`, "data-amount": String(shares[i]), text: formatAmount(shares[i], me.minor_units, me.currency) })))));
  }

  const form = h("form", { class: "card", novalidate: true, "aria-labelledby": "split-title" },
    h("h2", { id: "split-title", text: "Split a bill" }),
    h("p", { class: "hint", text: "You already paid. Each other person gets a request for their share." }),
    h("div", { class: "field" }, h("label", { for: "split-amount", text: "Total amount" }), amount),
    h("div", { class: "field" }, h("label", { for: "split-handles", text: "Handles, separated by commas" }), handles),
    h("div", { class: "field" }, h("label", { for: "split-note", text: "Note (optional)" }), note),
    preview, notices,
    h("div", { class: "form-actions" }, submit));
  for (const input of [amount, handles]) input.addEventListener("input", renderPreview);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return busy(submit, async () => {
      feedback.clear();
      const minor = readAmount(amount.value, me, feedback);
      if (minor === null) return;
      const names = parseHandles(handles.value);
      if (names.length === 0) return feedback.showError("Add at least one handle.", "Check the handles");
      await runWrite({
        path: "/splits", scope: "split", fingerprint: { amount: amount.value, handles: handles.value, note: note.value },
        body: { amount: minor, participant_handles: names, note: note.value }, what: "split", feedback,
        onSuccess: async (split) => { feedback.showSuccess(`Split sent: ${split.requests.length} request(s) created.`); showCreated(split); await refresh(); },
      });
    });
  });

  function showCreated(split) {
    created.replaceChildren(h("section", { class: "card", "aria-labelledby": "created-title" },
      h("h2", { id: "created-title", text: "Requests created" }),
      split.requests.length === 0
        ? h("p", { class: "hint", text: "Only you were in this split, so nobody owes anything." })
        : h("ul", { class: "list" }, split.requests.map((r) => h("li", { class: "row" },
            h("div", { class: "row-head" },
              h("span", { class: "row-title", text: `${at(r.payer_handle)} owes you` }),
              h("span", { class: "row-amount", text: money(r.amount, me) })))))));
  }

  layout = [strip.el, h("h1", { class: "page-title", text: "Split" }), h("div", { class: "columns even" }, form, created)];
  refresh();
}

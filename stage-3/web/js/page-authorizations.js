import { chip, h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { at, formatTime, money, timeEl } from "./format.js";
import { formatDecimal } from "./money.js";
import { createRefresher } from "./refresh.js";
import { authorizationChip, isQuiet } from "./status.js";
import { createTransferForm } from "./transferForm.js";
import { createWalletStrip } from "./wallet.js";
import { busy, readAmount, runWrite } from "./writes.js";

const LIMIT = 200;

export function mountAuthorizationsPage(shell) {
  let me = null;
  let layout = [];
  const drafts = new Map(); // authorization id -> {amount, keep}: typed capture values survive a refresh
  const strip = createWalletStrip();
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: "authorization-error", uncertain: "authorization-uncertain", success: "authorization-success" });
  const listHost = h("div", { class: "stack" });

  const refresh = createRefresher({ me: "/me", list: `/authorizations?limit=${LIMIT}` },
    ({ me: next, list }) => {
      me = next;
      if (!strip.el.isConnected) shell.main.replaceChildren(...layout);
      shell.showSignedIn(me);
      strip.update(me);
      renderList(list.authorizations);
      shell.setBusy(false);
    },
    () => (me ? strip.showRefreshFailed() : shell.main.replaceChildren(h("div", { class: "empty", role: "alert" },
      h("strong", { text: "We could not load your authorisations" }), h("button", { type: "button", text: "Try again", onclick: () => location.reload() })))),
  );

  function renderList(items) {
    if (items.length === 0) {
      listHost.replaceChildren(h("div", { class: "empty", testid: "empty-authorizations" },
        h("strong", { text: "No authorisations yet" }),
        h("p", { text: "Place a hold above to reserve money for someone. They can capture it later, in full or in parts." })));
      return;
    }
    listHost.replaceChildren(h("ul", { class: "list", testid: "authorization-list" }, items.map(item)));
  }

  function captureControls(a) {
    const draft = drafts.get(a.authorization_id) || { amount: formatDecimal(a.remaining_amount, me.minor_units), keep: false };
    const amount = h("input", { id: `capture-amount-${a.authorization_id}`, testid: `authorization-capture-amount-${a.authorization_id}`, type: "text", inputmode: "decimal", autocomplete: "off", value: draft.amount });
    const keep = h("input", { id: `capture-keep-${a.authorization_id}`, type: "checkbox" });
    keep.checked = draft.keep;
    const remember = () => drafts.set(a.authorization_id, { amount: amount.value, keep: keep.checked });
    amount.addEventListener("input", remember);
    keep.addEventListener("change", remember);
    const capture = h("button", { type: "button", testid: `authorization-capture-${a.authorization_id}`, text: "Capture", data: { variant: "primary" } });
    capture.addEventListener("click", () => busy(capture, async () => {
      feedback.clear();
      const minor = readAmount(amount.value, me, feedback);
      if (minor === null) return;
      const body = keep.checked ? { amount: minor, final: false } : { amount: minor };
      await runWrite({
        path: `/authorizations/${a.authorization_id}/capture`, body, what: "capture", feedback,
        scope: `capture:${a.authorization_id}`,
        fingerprint: { amount: amount.value, keep: keep.checked, remaining: a.remaining_amount },
        onSuccess: async () => { drafts.delete(a.authorization_id); feedback.showSuccess(`Captured ${money(minor, me)} from ${at(a.from_handle)}.`); await refresh(); },
        onRefused: refresh,
      });
    }));
    return h("div", { class: "row-actions" },
      h("div", { class: "field" }, h("label", { for: amount.id, text: "Amount to capture" }), amount),
      h("div", { class: "check" }, keep, h("label", { for: keep.id, text: "Keep the rest on hold" })),
      capture);
  }

  function voidControl(a) {
    const button = h("button", { type: "button", testid: `authorization-void-${a.authorization_id}`, text: "Void hold" });
    button.addEventListener("click", () => busy(button, async () => {
      feedback.clear();
      await runWrite({
        path: `/authorizations/${a.authorization_id}/void`, body: {}, what: "void", feedback,
        onSuccess: async () => { feedback.showSuccess(`Released the hold for ${at(a.to_handle)}.`); await refresh(); },
        onRefused: refresh, onUncertain: refresh,
      });
    }));
    return h("div", { class: "row-actions" }, button);
  }

  function item(a) {
    const outgoing = a.from_user_id === me.user_id;
    const isOpen = a.status === "open";
    const captured = a.captured_amount > 0;
    const vis = a.visibility === "private" ? chip("lock", "Private") : chip("globe", "Public");
    return h("li", { class: "row", testid: `authorization-item-${a.authorization_id}`, data: { status: a.status, quiet: isQuiet(a.status) } },
      h("div", { class: "row-head" },
        h("span", { class: "row-title", text: outgoing ? `Hold for ${at(a.to_handle)}` : `Hold from ${at(a.from_handle)}` }),
        h("span", { class: "row-amount", testid: `authorization-amount-${a.authorization_id}`, text: money(a.amount, me) })),
      h("p", { class: "note-line", text: a.note }),
      h("div", { class: "row-meta" }, authorizationChip(a.status), vis, h("span", { text: outgoing ? "You are holding" : "You can collect" }), timeEl(h, a.created_at)),
      a.status === "captured" && h("p", { class: "row-meta" }, h("span", { text: "Captured" }),
        h("span", { class: "num", testid: `authorization-captured-${a.authorization_id}`, text: money(a.captured_amount, me) })),
      captured && a.status !== "captured" && h("p", { class: "hint", text: `Captured so far ${money(a.captured_amount, me)}${isOpen ? `, ${money(a.remaining_amount, me)} still on hold` : ""}.` }),
      h("p", { class: "row-meta" }, h("span", { text: `${isOpen ? "Expires" : "Expiry"} ${formatTime(a.expires_at)}` }),
        h("span", { class: "tech", testid: `authorization-expires-${a.authorization_id}`, text: a.expires_at })),
      isOpen && !outgoing && captureControls(a),
      isOpen && outgoing && voidControl(a));
  }

  const getMe = () => me;
  const authorize = createTransferForm({
    prefix: "authorize", title: "Authorise a payment", intro: "Hold money for someone to collect later. Nothing moves until they capture it.",
    submitLabel: "Place hold", path: "/authorizations", what: "authorisation", variant: "primary",
    success: (amount, who) => `Holding ${amount} for ${who}.`, getMe, onDone: refresh,
  });

  layout = [
    strip.el,
    h("h1", { class: "page-title", text: "Authorizations" }),
    h("div", { class: "columns" },
      authorize.el,
      h("section", { class: "stack", "aria-labelledby": "authz-title" }, h("h2", { id: "authz-title", text: "Holds" }), notices, listHost)),
  ];
  refresh();
}

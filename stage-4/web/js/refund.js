import * as api from "./api.js";
import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { at, money } from "./format.js";
import { refundRefusalText } from "./messages.js";
import { formatDecimal } from "./money.js";
import { classify } from "./outcome.js";
import { currentAmount, remainder } from "./refund-math.js";
import { busy, readAmount, runWrite } from "./writes.js";

// createRefundControls keeps each payment's draft, open state, last notice and read corrected
// amount here, so a feed refresh that rebuilds the rows never loses what the person typed or
// what the service answered. The idempotency key follows the attempt (payment + amount text).
export function createRefundControls({ getMe, onDone }) {
  const states = new Map();
  const stateOf = (id) => {
    if (!states.has(id)) states.set(id, { open: false, amount: null, notice: null, current: null });
    return states.get(id);
  };

  async function learnCurrentAmount(id) {
    const res = await api.get(`/payments/${id}/revisions`);
    if (classify(res) === "success") stateOf(id).current = currentAmount(res.json.revisions);
  }

  function controlFor(p, refunded) {
    const me = getMe();
    const st = stateOf(p.payment_id);
    const left = remainder(p.amount, st.current, refunded);
    const id = (n) => `refund-${n}-${p.payment_id}`;
    const wrap = h("div", { class: "refund", testid: `refund-${p.payment_id}` });
    const notices = h("div", { class: "stack" });
    const shown = createFeedback(notices, { error: id("error"), uncertain: id("uncertain"), success: id("success") });
    const feedback = {
      clear: () => { shown.clear(); st.notice = null; },
      showError: (text, title) => { shown.showError(text, title); st.notice = { kind: "error", text, title }; },
      showUncertain: (text) => { shown.showUncertain(text); st.notice = { kind: "uncertain", text }; },
      showSuccess: (text) => { shown.showSuccess(text); st.notice = { kind: "success", text }; },
    };
    if (st.notice) {
      const { kind, text, title } = st.notice;
      if (kind === "error") shown.showError(text, title);
      else if (kind === "uncertain") shown.showUncertain(text);
      else shown.showSuccess(text);
    }
    if (left === 0) {
      wrap.append(h("p", { class: "hint", testid: id("done"), text: "Nothing left to refund on this payment." }), notices);
      return wrap;
    }

    const toggle = h("button", { type: "button", testid: id("toggle"), text: "Refund", "aria-expanded": String(st.open), "aria-controls": id("panel") });
    const amount = h("input", { id: id("amount"), testid: id("amount"), type: "text", inputmode: "decimal", autocomplete: "off",
      value: st.amount ?? formatDecimal(left, me.minor_units) });
    amount.addEventListener("input", () => { st.amount = amount.value; });

    const send = h("button", { type: "button", testid: id("submit"), text: "Send refund", data: { variant: "primary" } });
    send.addEventListener("click", () => busy(send, async () => {
      feedback.clear();
      const minor = readAmount(amount.value, me, feedback);
      if (minor === null) return;
      await runWrite({
        path: `/payments/${p.payment_id}/refunds`, body: { amount: minor }, what: "refund", feedback, refusal: refundRefusalText,
        scope: `refund:${p.payment_id}`, fingerprint: { amount: amount.value },
        onSuccess: async () => {
          st.amount = null;
          feedback.showSuccess(`Refunded ${money(minor, me)} to ${at(p.from_handle)}.`);
          await onDone();
        },
        onRefused: async (res) => {
          if (res.json?.error?.code === "refund_exceeds_payment") await learnCurrentAmount(p.payment_id);
          await onDone();
        },
      });
    }));

    const panel = h("div", { class: "refund-panel", id: id("panel"), hidden: !st.open },
      h("p", { class: "hint", testid: id("limit"), text: `Up to ${money(left, me)} can still be refunded to ${at(p.from_handle)}.` }),
      h("div", { class: "row-actions" }, h("div", { class: "field" }, h("label", { for: id("amount"), text: "Refund amount" }), amount), send),
      notices);
    toggle.addEventListener("click", () => {
      st.open = !st.open;
      panel.hidden = !st.open;
      toggle.setAttribute("aria-expanded", String(st.open));
    });
    wrap.append(toggle, panel);
    return wrap;
  }

  return { controlFor };
}

import { h } from "./dom.js";
import { money } from "./format.js";

function amountEl(testid, cls) {
  return h("span", { testid, class: cls, "data-amount": "0" });
}

// createWalletStrip: available is the headline; total and held are secondary.
// Labels are siblings of the testid elements so each testid text is exactly the amount.
export function createWalletStrip({ onRefresh } = {}) {
  const available = amountEl("wallet-available", "wallet-available");
  const total = amountEl("wallet-balance", "value");
  const held = amountEl("wallet-held", "value");
  const heldBlock = h("div", {}, h("span", { class: "wallet-label", text: "On hold" }), held);
  const secondary = h("div", { class: "wallet-secondary" }, h("div", {}, h("span", { class: "wallet-label", text: "Total" }), total));
  const status = h("p", { class: "hint", role: "status" });
  const el = h("section", { class: "wallet", "aria-label": "Wallet", "aria-live": "polite" },
    h("div", { class: "wallet-headline" }, h("span", { class: "wallet-label", text: "Available to spend" }), available),
    secondary, status);

  let refreshButton;
  if (onRefresh) {
    refreshButton = h("button", { type: "button", testid: "wallet-refresh", text: "Refresh", onclick: async () => {
      if (refreshButton.getAttribute("aria-busy") === "true") return;
      refreshButton.setAttribute("aria-busy", "true");
      try { await onRefresh(); } finally { refreshButton.removeAttribute("aria-busy"); }
    } });
    el.append(h("div", { class: "wallet-actions" }, refreshButton));
  }

  const set = (node, minor, me) => {
    node.textContent = money(minor, me);
    node.setAttribute("data-amount", String(minor));
  };

  return {
    el,
    update(me) {
      set(available, me.available, me);
      set(total, me.total, me);
      if (me.held > 0) {
        set(held, me.held, me);
        if (!heldBlock.isConnected) secondary.append(heldBlock);
      } else heldBlock.remove();
      status.textContent = "";
    },
    showRefreshFailed() {
      status.textContent = "Could not reach Pocketful. These numbers may be out of date. Refresh to try again.";
    },
  };
}

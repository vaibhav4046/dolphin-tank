import * as api from "./api.js";
import { renderActivity } from "./activity.js";
import { h } from "./dom.js";
import { createRefresher } from "./refresh.js";
import { createRefundControls } from "./refund.js";
import { createRequestForm } from "./requestForm.js";
import { createTransferForm } from "./transferForm.js";
import { createWalletStrip } from "./wallet.js";
import { classify } from "./outcome.js";

const PAGE_SIZE = 50;

export function mountWalletPage(shell) {
  let me = null;
  let layout = [];
  const feedHost = h("div", { class: "stack" });
  const strip = createWalletStrip({ onRefresh: () => refresh() });
  const refunds = createRefundControls({ getMe: () => me, onDone: () => refresh() });

  const refresh = createRefresher(
    { me: "/me", activity: `/activity?limit=${PAGE_SIZE}` },
    ({ me: nextMe, activity }) => {
      me = nextMe;
      if (!strip.el.isConnected) shell.main.replaceChildren(...layout);
      shell.showSignedIn(me);
      strip.update(me);
      renderActivity(feedHost, activity.payments, activity.has_more, me, loadOlder, refunds);
      shell.setBusy(false);
    },
    () => (me ? strip.showRefreshFailed() : showLoadFailure()),
  );

  async function loadOlder(offset) {
    const res = await api.get(`/activity?limit=${PAGE_SIZE}&offset=${offset}`);
    return classify(res) === "success" ? res.json : null;
  }

  function showLoadFailure() {
    shell.setBusy(false);
    shell.main.replaceChildren(h("div", { class: "empty", role: "alert" },
      h("strong", { text: "We could not load your wallet" }),
      h("p", { text: "Check your connection, then try again." }),
      h("button", { type: "button", text: "Try again", onclick: () => location.reload() })));
  }

  const getMe = () => me;
  const pay = createTransferForm({
    prefix: "pay", title: "Pay someone", intro: "Money moves straight away, from your available funds.",
    submitLabel: "Send payment", path: "/payments", what: "payment", variant: "primary",
    success: (amount, who) => `Sent ${amount} to ${who}.`, getMe, onDone: refresh,
  });
  const authorize = createTransferForm({
    prefix: "authorize", title: "Authorise a payment", intro: "Hold money for someone to collect later. Nothing moves until they capture it.",
    submitLabel: "Place hold", path: "/authorizations", what: "authorisation", variant: "secondary",
    success: (amount, who) => `Holding ${amount} for ${who}.`, getMe, onDone: refresh,
  });
  const request = createRequestForm({ getMe, onDone: refresh });

  layout = [
    strip.el,
    h("div", { class: "columns" },
      h("div", { class: "stack" }, pay.el, request.el, authorize.el),
      h("section", { class: "stack", "aria-labelledby": "feed-title" },
        h("div", { class: "section-head" }, h("h2", { id: "feed-title", text: "Activity" })),
        feedHost)),
  ];
  refresh();
}

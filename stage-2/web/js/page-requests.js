import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { at, money, timeEl } from "./format.js";
import { createRefresher } from "./refresh.js";
import { requestChip, isQuiet } from "./status.js";
import { busy, runWrite } from "./writes.js";
import { createWalletStrip } from "./wallet.js";

const LIMIT = 200;

export function mountRequestsPage(shell) {
  let me = null;
  let layout = [];
  const strip = createWalletStrip();
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: "request-error", uncertain: "request-uncertain" });
  const incoming = h("ul", { class: "list", testid: "incoming-list" });
  const outgoing = h("ul", { class: "list", testid: "outgoing-list" });
  const empty = h("div", { class: "empty", testid: "empty-requests" },
    h("strong", { text: "No requests yet" }),
    h("p", { text: "Requests you send or receive appear here. Ask someone for money from the Wallet page, or split a bill." }),
    h("a", { href: "/split", text: "Split a bill" }));

  const refresh = createRefresher(
    { me: "/me", incoming: `/requests?direction=incoming&limit=${LIMIT}`, outgoing: `/requests?direction=outgoing&limit=${LIMIT}` },
    (data) => {
      me = data.me;
      if (!strip.el.isConnected) shell.main.replaceChildren(...layout);
      shell.showSignedIn(me);
      strip.update(me);
      fill(incoming, data.incoming.requests, "incoming");
      fill(outgoing, data.outgoing.requests, "outgoing");
      empty.hidden = data.incoming.requests.length + data.outgoing.requests.length > 0;
      shell.setBusy(false);
    },
    () => (me ? strip.showRefreshFailed() : failed()),
  );

  function fill(list, requests, direction) {
    const rows = requests.map((r) => row(r, direction));
    list.replaceChildren(...(rows.length ? rows : [h("li", { class: "hint", text: `No ${direction} requests.` })]));
  }

  function failed() {
    shell.setBusy(false);
    shell.main.replaceChildren(h("div", { class: "empty", role: "alert" },
      h("strong", { text: "We could not load your requests" }),
      h("button", { type: "button", text: "Try again", onclick: () => location.reload() })));
  }

  const act = (button, path) => busy(button, () =>
    runWrite({ path, body: {}, what: "change", feedback, onSuccess: refresh, onRefused: refresh, onUncertain: refresh }));

  function payControls(r) {
    const visibility = h("select", { id: `request-visibility-${r.request_id}` },
      h("option", { value: "public", text: "Public" }), h("option", { value: "private", text: "Private" }));
    const pay = h("button", { type: "button", testid: `request-pay-${r.request_id}`, text: "Pay", data: { variant: "primary" } });
    pay.addEventListener("click", () => busy(pay, () => runWrite({
      path: `/requests/${r.request_id}/pay`, body: { visibility: visibility.value },
      scope: `pay-request:${r.request_id}`, fingerprint: { visibility: visibility.value },
      what: "payment", feedback, onSuccess: refresh, onRefused: refresh,
    })));
    const decline = h("button", { type: "button", testid: `request-decline-${r.request_id}`, text: "Decline" });
    decline.addEventListener("click", () => act(decline, `/requests/${r.request_id}/decline`));
    return [
      h("div", { class: "field" }, h("label", { for: `request-visibility-${r.request_id}`, text: "Visibility" }), visibility),
      pay, decline,
    ];
  }

  function row(r, direction) {
    const isIncoming = direction === "incoming";
    const counterpart = isIncoming ? r.requester_handle : r.payer_handle;
    let actions = [];
    if (r.status === "pending" && isIncoming) actions = payControls(r);
    if (r.status === "pending" && !isIncoming) {
      const cancel = h("button", { type: "button", testid: `request-cancel-${r.request_id}`, text: "Cancel request" });
      cancel.addEventListener("click", () => act(cancel, `/requests/${r.request_id}/cancel`));
      actions = [cancel];
    }
    return h("li", { class: "row", testid: `request-item-${r.request_id}`, data: { status: r.status, quiet: isQuiet(r.status) } },
      h("div", { class: "row-head" },
        h("span", { class: "row-title", text: isIncoming ? `${at(counterpart)} asks you for` : `You asked ${at(counterpart)} for` }),
        h("span", { class: "row-amount", testid: `request-amount-${r.request_id}`, text: money(r.amount, me) })),
      h("p", { class: "note-line", text: r.note }),
      h("div", { class: "row-meta" }, requestChip(r.status), timeEl(h, r.created_at), h("span", { class: "tech", text: r.request_id })),
      actions.length > 0 && h("div", { class: "row-actions" }, actions));
  }

  layout = [
    strip.el,
    h("h1", { class: "page-title", text: "Requests" }),
    notices,
    empty,
    h("div", { class: "columns even" },
      h("section", { class: "stack", "aria-labelledby": "incoming-title" }, h("h2", { id: "incoming-title", text: "Incoming" }), incoming),
      h("section", { class: "stack", "aria-labelledby": "outgoing-title" }, h("h2", { id: "outgoing-title", text: "Outgoing" }), outgoing)),
  ];
  refresh();
}

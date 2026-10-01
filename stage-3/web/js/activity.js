import { chip, h } from "./dom.js";
import { at, money, timeEl } from "./format.js";

function direction(p, me) {
  if (p.from_user_id === me.user_id) return { label: "Sent", glyph: "ring", text: `You paid ${at(p.to_handle)}` };
  if (p.to_user_id === me.user_id) return { label: "Received", glyph: "disc", text: `${at(p.from_handle)} paid you` };
  return { label: "Between others", glyph: "dash", text: `${at(p.from_handle)} paid ${at(p.to_handle)}` };
}

function origin(p) {
  if (p.authorization_id) return "Collected from an authorisation";
  if (p.request_id) return "Pays a request";
  return null;
}

function item(p, me) {
  const dir = direction(p, me);
  const vis = p.visibility === "private" ? chip("lock", "Private") : chip("globe", "Public");
  const meta = h("div", { class: "row-meta" }, chip(dir.glyph, dir.label), vis, timeEl(h, p.created_at), origin(p) && h("span", { text: origin(p) }));
  return h("li", { class: "row", testid: `activity-item-${p.payment_id}`, data: { visibility: p.visibility } },
    h("div", { class: "row-head" },
      h("span", { class: "row-title", testid: `activity-parties-${p.payment_id}`, text: `${p.from_handle} → ${p.to_handle}` }),
      h("span", { class: "row-amount", testid: `activity-amount-${p.payment_id}`, text: money(p.amount, me) })),
    h("p", { class: "hint", text: dir.text }),
    h("p", { class: "note-line", testid: `activity-note-${p.payment_id}`, text: p.note }),
    meta);
}

export function renderActivity(host, payments, hasMore, me, onMore) {
  host.replaceChildren();
  if (payments.length === 0) {
    host.append(h("div", { class: "empty", testid: "empty-activity" },
      h("strong", { text: "No payments to show yet" }),
      h("p", { text: "When you send or receive money it appears here, newest first." })));
    return;
  }
  const list = h("ul", { class: "list", testid: "activity-list" }, payments.map((p) => item(p, me)));
  host.append(list);
  if (hasMore) {
    const more = h("button", { type: "button", text: "Show older", onclick: async () => {
      if (more.getAttribute("aria-busy") === "true") return;
      more.setAttribute("aria-busy", "true");
      const next = await onMore(payments.length);
      more.removeAttribute("aria-busy");
      if (next) {
        for (const p of next.payments) list.append(item(p, me));
        payments.push(...next.payments);
        if (!next.has_more) more.remove();
      }
    } });
    host.append(more);
  }
}

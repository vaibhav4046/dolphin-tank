import { glyph, h } from "./dom.js";

// createFeedback manages the error / uncertain / success notices of one form or page region.
// Elements exist in the DOM only while they carry a message.
export function createFeedback(host, { error, uncertain, success } = {}) {
  let els = {};

  const drop = (kind) => {
    els[kind]?.remove();
    delete els[kind];
  };

  const show = (kind, testid, role, glyphKind, title, text) => {
    clear();
    const body = h("span", {}, title && h("span", { class: "notice-title", text: title }), h("span", { text }));
    const el = h("p", { class: "notice", data: { kind }, role, testid }, glyph(glyphKind), body);
    els[kind] = el;
    host.append(el);
  };

  function clear() {
    for (const kind of Object.keys(els)) drop(kind);
  }

  return {
    clear,
    showError: (text, title = "Not completed") => show("refused", error, "alert", "cross", title, text),
    showUncertain: (text) => show("uncertain", uncertain || error + "-uncertain", "status", "dashed", "Unconfirmed", text),
    showSuccess: (text) => show("success", success, "status", "disc", null, text),
  };
}

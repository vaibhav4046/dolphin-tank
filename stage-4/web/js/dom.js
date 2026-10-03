const SVG_NS = "http://www.w3.org/2000/svg";

// h(tag, attrs, ...children): attrs may hold testid, text, class, dataset entries and plain attributes.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "testid") el.setAttribute("data-testid", value);
    else if (name === "text") el.textContent = value;
    else if (name === "data") for (const [k, v] of Object.entries(value)) el.dataset[k] = v;
    else if (name.startsWith("on")) el.addEventListener(name.slice(2), value);
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child);
  }
  return el;
}

export function replaceChildren(el, ...children) {
  el.replaceChildren(...children.flat().filter(Boolean));
}

const GLYPHS = {
  ring: '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/>',
  disc: '<circle cx="6" cy="6" r="5" fill="currentColor"/>',
  dashed: '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.2 1.8"/>',
  cross: '<path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  slash: '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2.8 9.2l6.4-6.4" stroke="currentColor" stroke-width="1.5"/>',
  dash: '<path d="M2 6h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  globe: '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M1.5 6h9M6 1.5c-2 2.2-2 6.8 0 9M6 1.5c2 2.2 2 6.8 0 9" fill="none" stroke="currentColor" stroke-width="1.1"/>',
  return: '<path d="M4.5 2.2L2 4.8l2.5 2.6M2 4.8h5.3a2.7 2.7 0 010 5.4H5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
  lock: '<rect x="2.2" y="5.2" width="7.6" height="5.2" rx="1" fill="currentColor"/><path d="M4 5.2V4a2 2 0 014 0v1.2" fill="none" stroke="currentColor" stroke-width="1.4"/>',
};

export function glyph(kind) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 12 12");
  svg.setAttribute("class", "glyph");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = GLYPHS[kind] || GLYPHS.ring;
  return svg;
}

export function chip(kind, label, tone) {
  return h("span", { class: "chip", data: tone ? { tone } : {} }, glyph(kind), h("span", { text: label }));
}

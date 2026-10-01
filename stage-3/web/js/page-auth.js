import * as api from "./api.js";
import { h } from "./dom.js";
import { createFeedback } from "./feedback.js";
import { refusalText } from "./messages.js";
import { classify } from "./outcome.js";
import { goTo, setToken } from "./session.js";
import { busy } from "./writes.js";

const field = (id, label, input) => h("div", { class: "field" }, h("label", { for: id, text: label }), input);

const FORMS = {
  login: {
    title: "Log in", intro: "Welcome back. Sign in to see your wallet.", path: "/auth/login", submit: "Log in",
    other: h("p", { class: "hint" }, "New here? ", h("a", { href: "/signup", text: "Create an account" }), "."),
    fields: [
      ["email", "Email", { type: "email", autocomplete: "username", inputmode: "email" }],
      ["password", "Password", { type: "password", autocomplete: "current-password" }],
    ],
  },
  signup: {
    title: "Create your account", intro: "Your handle comes from your email address.", path: "/auth/signup", submit: "Sign up",
    other: h("p", { class: "hint" }, "Already have an account? ", h("a", { href: "/login", text: "Log in" }), "."),
    fields: [
      ["email", "Email", { type: "email", autocomplete: "username", inputmode: "email" }],
      ["password", "Password (at least 8 characters)", { type: "password", autocomplete: "new-password" }],
      ["display-name", "Display name", { type: "text", autocomplete: "name" }],
    ],
  },
};

// mountAuthPage renders the login or signup form; the shell handles the signed-in header separately.
export function mountAuthPage(shell, kind) {
  const spec = FORMS[kind];
  const inputs = Object.fromEntries(spec.fields.map(([name, , attrs]) =>
    [name, h("input", { id: `${kind}-${name}`, testid: `${kind}-${name}`, ...attrs })]));
  const notices = h("div", { class: "stack" });
  const feedback = createFeedback(notices, { error: "auth-error", uncertain: "auth-uncertain" });
  const submit = h("button", { type: "submit", testid: `${kind}-submit`, text: spec.submit, data: { variant: "primary" } });

  const form = h("form", { class: "card", novalidate: true, "aria-labelledby": "auth-title" },
    h("h1", { id: "auth-title", class: "page-title", text: spec.title }),
    h("p", { class: "hint", text: spec.intro }),
    spec.fields.map(([name, label]) => field(`${kind}-${name}`, label, inputs[name])),
    notices,
    h("div", { class: "form-actions" }, submit),
    spec.other);

  for (const input of Object.values(inputs)) input.addEventListener("input", feedback.clear);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return busy(submit, async () => {
      feedback.clear();
      const body = Object.fromEntries(spec.fields.map(([name]) =>
        [name.replace("-", "_"), name === "password" ? inputs[name].value : inputs[name].value.trim()]));
      const res = await api.request("POST", spec.path, { body, auth: false });
      const outcome = res.status === 401 ? "refused" : classify(res);
      if (outcome === "success") {
        setToken(res.json.token);
        goTo("/");
      } else if (outcome === "refused") {
        feedback.showError(refusalText(res.json), "Could not sign you in");
      } else {
        feedback.showUncertain("We could not reach Pocketful, so we do not know whether this worked. Try again.");
      }
    });
  });

  shell.main.replaceChildren(h("div", { class: "auth-wrap" }, form));
  shell.setBusy(false);
}

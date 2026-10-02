import { h, replaceChildren } from "./dom.js";
import { clearToken, getToken, goToLogin } from "./session.js";

// The nav and brand are static HTML; the shell fills the session area and marks the active link.
export function createShell() {
  const session = document.getElementById("session");
  const main = document.getElementById("main");

  function setActive(path) {
    for (const a of document.querySelectorAll("[data-nav]")) {
      if (a.dataset.nav === path) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
  }

  function showSignedOut() {
    replaceChildren(session, h("a", { href: "/login", text: "Log in" }), h("a", { href: "/signup", text: "Sign up" }));
  }

  function showSignedIn(me) {
    const logout = h("button", {
      type: "button",
      testid: "logout-button",
      text: "Log out",
      onclick: () => {
        clearToken();
        goToLogin();
        if (location.pathname === "/login") location.reload();
      },
    });
    const who = h("div", { class: "who" },
      h("span", { testid: "current-user", text: me.display_name }),
      h("span", { class: "tech" }, "@", h("span", { testid: "current-handle", text: me.handle })));
    replaceChildren(session, who, logout);
  }

  function setBusy(isBusy) {
    main.setAttribute("aria-busy", isBusy ? "true" : "false");
  }

  return { main, setActive, showSignedOut, showSignedIn, setBusy, isSignedIn: () => Boolean(getToken()) };
}

import * as api from "./api.js";
import { mountAuthorizationsPage } from "./page-authorizations.js";
import { mountAuthPage } from "./page-auth.js";
import { mountRequestsPage } from "./page-requests.js";
import { mountSplitPage } from "./page-split.js";
import { mountWalletPage } from "./page-wallet.js";
import { classify } from "./outcome.js";
import { getToken, goToLogin } from "./session.js";
import { createShell } from "./shell.js";

const TITLES = { "/": "Wallet", "/requests": "Requests", "/split": "Split", "/authorizations": "Authorizations", "/login": "Log in", "/signup": "Sign up" };

const PROTECTED = {
  "/": mountWalletPage,
  "/requests": mountRequestsPage,
  "/split": mountSplitPage,
  "/authorizations": mountAuthorizationsPage,
};

async function showSessionOnAuthPages(shell) {
  if (!getToken()) return shell.showSignedOut();
  const res = await api.get("/me");
  if (classify(res) === "success") shell.showSignedIn(res.json);
  else shell.showSignedOut();
}

function boot() {
  const path = location.pathname;
  const shell = createShell();
  document.title = `${TITLES[path] || "Pocketful"} · Pocketful`;
  shell.setActive(path);
  if (path === "/login" || path === "/signup") {
    mountAuthPage(shell, path.slice(1));
    showSessionOnAuthPages(shell);
    return;
  }
  const mount = PROTECTED[path];
  if (!mount) return;
  if (!getToken()) {
    goToLogin();
    return;
  }
  mount(shell);
}

boot();

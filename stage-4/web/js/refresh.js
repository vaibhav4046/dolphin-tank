import * as api from "./api.js";
import { createLatestWins } from "./latest.js";
import { classify } from "./outcome.js";

// createRefresher returns refresh(): it loads every path in parallel and applies the result only
// if no later refresh has begun, so a delayed earlier read never overwrites a newer one.
//   paths   {name: path}
//   apply   ({name: json}) -> void, on a fully successful read
//   fail    () -> void, when the newest read could not be completed
export function createRefresher(paths, apply, fail) {
  const latest = createLatestWins();
  const names = Object.keys(paths);
  return async function refresh() {
    const token = latest.begin();
    const results = await Promise.all(names.map((n) => api.get(paths[n])));
    if (!latest.isCurrent(token)) return;
    if (results.some((r) => classify(r) === "unauthenticated")) return;
    if (results.some((r) => classify(r) !== "success")) {
      fail();
      return;
    }
    apply(Object.fromEntries(names.map((n, i) => [n, results[i].json])));
  };
}

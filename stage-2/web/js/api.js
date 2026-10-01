import { clearToken, getToken, goToLogin } from "./session.js";

const TIMEOUT_MS = 8000;

// request resolves to the shape outcome.classify expects: {networkError, status, json}.
// It never throws; a 401 on an authenticated call clears the token and goes to /login.
export async function request(method, path, { body, key, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (key) headers["Idempotency-Key"] = key;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    let json;
    try {
      json = await res.json();
    } catch {
      json = undefined;
    }
    if (res.status === 401 && auth) {
      clearToken();
      goToLogin();
    }
    return { status: res.status, json };
  } catch {
    return { networkError: true };
  } finally {
    clearTimeout(timer);
  }
}

export const get = (path) => request("GET", path);

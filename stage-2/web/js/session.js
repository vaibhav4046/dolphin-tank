const TOKEN_KEY = "pocketful.token";
const AUTH_PATHS = ["/login", "/signup"];

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);
export const goTo = (path) => location.assign(path);
export const goToLogin = () => {
  if (!AUTH_PATHS.includes(location.pathname)) location.replace("/login");
};

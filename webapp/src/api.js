const API = window.location.origin;

function getToken() {
  return localStorage.getItem("cbdc_token");
}

export function setToken(token) {
  localStorage.setItem("cbdc_token", token);
}

export function clearToken() {
  localStorage.removeItem("cbdc_token");
}

export function isLoggedIn() {
  return !!getToken();
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const message = data?.detail || `Request failed (${res.status})`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

export const api = {
  signup: (org_name, email, password) =>
    request("/auth/signup", { method: "POST", body: { org_name, email, password }, auth: false }),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => request("/me"),
  listKeys: () => request("/auth/keys"),
  createKey: () => request("/auth/keys", { method: "POST" }),
  revokeKey: (id) => request(`/auth/keys/${id}`, { method: "DELETE" }),
  sendTransaction: (body) => request("/transaction", { method: "POST", body }),
  listTransactions: () => request("/transactions"),
  listAlerts: () => request("/alerts"),
  stats: () => request("/stats"),
};

export function wsUrl() {
  return API.replace(/^http/, "ws") + "/ws/live";
}

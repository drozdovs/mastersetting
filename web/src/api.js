/* Клиент API админки: хранит токен, добавляет заголовок, единая обработка ошибок. */

const TOKEN_KEY = "ms_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function isAuthed() {
  return Boolean(getToken());
}

async function request(path, { method = "GET", body, isForm } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let payload = body;
  if (body && !isForm) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const resp = await fetch(path, { method, headers, body: payload });
  if (resp.status === 401) {
    setToken("");
    throw new Error("Не авторизован");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = data.detail || detail;
    } catch (e) {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : resp.text();
}

export const api = {
  login: (login, password) =>
    request("/api/auth/login", { method: "POST", body: { login, password } }),
  me: () => request("/api/auth/me"),

  users: () => request("/api/users"),
  createUser: (data) => request("/api/users", { method: "POST", body: data }),
  updateUser: (id, data) =>
    request(`/api/users/${id}`, { method: "PATCH", body: data }),
  deleteUser: (id) => request(`/api/users/${id}`, { method: "DELETE" }),

  groups: () => request("/api/groups"),
  createGroup: (data) => request("/api/groups", { method: "POST", body: data }),
  deleteGroup: (id) => request(`/api/groups/${id}`, { method: "DELETE" }),

  cameras: () => request("/api/cameras"),
  createCamera: (data) => request("/api/cameras", { method: "POST", body: data }),
  updateCamera: (id, data) =>
    request(`/api/cameras/${id}`, { method: "PATCH", body: data }),
  deleteCamera: (id) => request(`/api/cameras/${id}`, { method: "DELETE" }),

  agents: () => request("/api/agents"),
  events: (limit = 100) => request(`/api/events?limit=${limit}`),
  stats: () => request("/api/stats"),

  releases: () => request("/api/releases"),
  createRelease: (data) => request("/api/releases", { method: "POST", body: data }),
  publishRelease: (id) =>
    request(`/api/releases/${id}/publish`, { method: "POST" }),
  uploadRelease: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/releases/${id}/upload`, {
      method: "POST",
      body: form,
      isForm: true,
    });
  },
};

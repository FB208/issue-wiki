const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export function getToken() {
  return localStorage.getItem("issue-wiki-token") || "";
}

export function setToken(token) {
  if (token) localStorage.setItem("issue-wiki-token", token);
  else localStorage.removeItem("issue-wiki-token");
}

export function getGuestId() {
  let guestId = localStorage.getItem("issue-wiki-guest-id");
  if (!guestId) {
    guestId = crypto.randomUUID();
    localStorage.setItem("issue-wiki-guest-id", guestId);
  }
  return guestId;
}

export async function request(path, options = {}) {
  const token = getToken();
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Guest-Id", getGuestId());

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === "string" ? data : data.detail || "请求失败";
    throw new Error(message);
  }
  return data;
}

export function toQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      if (!value.length) search.append(key, "");
      else value.forEach((item) => search.append(key, item));
    } else {
      search.set(key, value);
    }
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request("/uploads", { method: "POST", body: formData });
}

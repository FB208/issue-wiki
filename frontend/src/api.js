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
    guestId = createGuestId();
    localStorage.setItem("issue-wiki-guest-id", guestId);
  }
  return guestId;
}

function createGuestId() {
  const webCrypto = globalThis.crypto;
  if (webCrypto?.randomUUID) return webCrypto.randomUUID();
  if (webCrypto?.getRandomValues) {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
  }
  return `guest-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
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

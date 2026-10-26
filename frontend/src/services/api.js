import { mockApi } from "./mockApi";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
export const MOCK_MODE = import.meta.env.VITE_MOCK_API === "true";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const raw = await response.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = raw;
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" ? data.detail || data.message : data;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const realApi = {
  health: () => request("/api/health"),
  guidelines: () => request("/api/guidelines"),
  createGuideline: (data) => request("/api/guidelines", json("POST", data)),
  deleteGuideline: (id) => request(`/api/guidelines/${encodeURIComponent(id)}`, { method: "DELETE" }),
  sources: () => request("/api/sources"),
  createSource: (data) => request("/api/sources", json("POST", data)),
  uploadSource: (data) => {
    const form = new FormData();
    form.append("file", data.file);
    if (data.name) form.append("name", data.name);
    if (data.guideline_id) form.append("guideline_id", data.guideline_id);
    if (data.url) form.append("url", data.url);
    if (data.source_date) form.append("source_date", data.source_date);
    if (data.expiry_date) form.append("expiry_date", data.expiry_date);
    return request("/api/sources/upload", { method: "POST", body: form });
  },
  deleteSource: (id) => request(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" }),
  analyze: (data) => data.file
    ? (() => {
        const form = new FormData();
        form.append("title", data.title);
        form.append("content", data.content);
        form.append("content_type", data.content_type);
        form.append("alt_text", data.alt_text || "");
        form.append("file", data.file);
        if (data.guideline_ids?.length) form.append("guideline_ids", JSON.stringify(data.guideline_ids));
        if (data.source_ids?.length) form.append("source_ids", JSON.stringify(data.source_ids));
        return request("/api/analyze", { method: "POST", body: form });
      })()
    : request("/api/analyze", json("POST", { title: data.title, content: data.content, content_type: data.content_type, guideline_ids: data.guideline_ids || [], source_ids: data.source_ids || [], alt_text: data.alt_text || "" })),
  reviewActivity: (id) => request(`/api/reviews/${encodeURIComponent(id)}/activity`),
  reviews: () => request("/api/reviews"),
  review: (id) => request(`/api/reviews/${encodeURIComponent(id)}`),
  updateStatus: (id, status) => request(`/api/reviews/${encodeURIComponent(id)}/status`, json("PATCH", { status })),
  addComment: (id, comment) => request(`/api/reviews/${encodeURIComponent(id)}/comments`, json("POST", { comment })),
  addRevision: (id, revision) => request(`/api/reviews/${encodeURIComponent(id)}/revisions`, json("POST", revision)),
  analytics: () => request("/api/analytics/summary"),
  blindSpots: () => request("/api/analytics/guideline-blind-spots"),
};

export const api = MOCK_MODE ? mockApi : realApi;
export function unwrapList(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.results)) return value.results;
  if (Array.isArray(value?.data)) return value.data;
  for (const key of ["guidelines", "reviews", "findings", "issues", "comments", "revisions"]) {
    if (Array.isArray(value?.[key])) return value[key];
  }
  return [];
}
export function errorMessage(error) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

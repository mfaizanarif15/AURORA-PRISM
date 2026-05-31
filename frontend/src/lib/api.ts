import type {
  AnalysisPayload,
  AnalysisRun,
  AuthProfilePayload,
  AuthSession,
  AuthUser,
  Clip,
  Episode,
  RenderedClip
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
let authToken = "";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorResponse = {
  detail?: unknown;
  message?: unknown;
};

type ValidationIssue = {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
};

function authQuery() {
  return authToken ? `token=${encodeURIComponent(authToken)}` : "";
}

function withAuthQuery(path: string) {
  const query = authQuery();
  if (!query) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${query}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });
  if (!response.ok) {
    const raw = await response.text();
    const message = apiErrorMessage(raw, response.statusText);
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function apiErrorMessage(raw: string, fallback = "Request failed") {
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as ErrorResponse;
    return formatErrorValue(parsed.detail) ?? formatErrorValue(parsed.message) ?? raw;
  } catch {
    return raw;
  }
}

function formatErrorValue(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const messages = value.map(formatErrorValue).filter(Boolean);
    return messages.length ? messages.join("\n") : null;
  }
  if (!value || typeof value !== "object") return null;

  const issue = value as ValidationIssue;
  if (issue.msg) return formatValidationIssue(issue);

  const nested = value as ErrorResponse;
  return formatErrorValue(nested.detail) ?? formatErrorValue(nested.message);
}

function formatValidationIssue(issue: ValidationIssue) {
  const label = validationFieldLabel(issue.loc);
  const minLength = typeof issue.ctx?.min_length === "number" ? issue.ctx.min_length : null;
  const maxLength = typeof issue.ctx?.max_length === "number" ? issue.ctx.max_length : null;

  if (issue.type === "string_too_short" && minLength !== null) {
    return `${label} must be at least ${minLength} characters.`;
  }
  if (issue.type === "string_too_long" && maxLength !== null) {
    return `${label} must be ${maxLength} characters or fewer.`;
  }
  return label ? `${label}: ${issue.msg}` : issue.msg ?? "Request validation failed";
}

function validationFieldLabel(loc?: Array<string | number>) {
  const path = loc?.filter((item) => item !== "body") ?? [];
  const field = path[path.length - 1];
  if (field === undefined) return "Field";
  return String(field)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export const api = {
  setAuthToken: (token: string) => {
    authToken = token;
  },
  login: (payload: { username: string; password: string }) =>
    request<AuthSession>("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  signup: (payload: { username: string; display_name?: string; password: string }) =>
    request<AuthSession>("/auth/signup", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<AuthUser>("/auth/me"),
  updateProfile: (payload: AuthProfilePayload) =>
    request<AuthSession>("/auth/me", { method: "PATCH", body: JSON.stringify(payload) }),
  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),
  episodes: () => request<Episode[]>("/episodes"),
  createEpisode: (payload: Partial<Episode>) =>
    request<Episode>("/episodes", { method: "POST", body: JSON.stringify(payload) }),
  updateEpisode: (episodeId: string, payload: Partial<Episode>) =>
    request<Episode>(`/episodes/${episodeId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteEpisode: (episodeId: string) =>
    request<{ status: string; episode_id: string }>(`/episodes/${episodeId}`, { method: "DELETE" }),
  autoTitleEpisode: (episodeId: string, ai_provider: AnalysisPayload["ai_provider"]) =>
    request<Episode>(`/episodes/${episodeId}/auto-title`, {
      method: "POST",
      body: JSON.stringify({ ai_provider })
    }),
  saveContext: (episodeId: string, payload: Record<string, unknown>) =>
    request(`/episodes/${episodeId}/context`, { method: "PATCH", body: JSON.stringify(payload) }),
  uploadAsset: (episodeId: string, form: FormData) =>
    request(`/episodes/${episodeId}/assets`, { method: "POST", body: form }),
  uploadTranscript: (episodeId: string, form: FormData) =>
    request(`/episodes/${episodeId}/transcript`, { method: "POST", body: form }),
  analyze: (episodeId: string, payload: AnalysisPayload) =>
    request<AnalysisRun>(`/episodes/${episodeId}/analyze`, { method: "POST", body: JSON.stringify(payload) }),
  clips: (episodeId: string, filters: { clip_type?: string; target_platform?: string; status?: string }) => {
    const params = new URLSearchParams();
    if (filters.clip_type) params.set("clip_type", filters.clip_type);
    if (filters.target_platform) params.set("target_platform", filters.target_platform);
    if (filters.status) params.set("status", filters.status);
    const suffix = params.toString() ? `?${params}` : "";
    return request<Clip[]>(`/episodes/${episodeId}/clips${suffix}`);
  },
  updateClipStatus: (clipId: string, status: string, comments = "", userName = "AURORA Demo") =>
    request<Clip>(`/clips/${clipId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, comments, user_name: userName })
    }),
  deleteClip: (clipId: string) =>
    request<{ status: string; clip_id: string }>(`/clips/${clipId}`, { method: "DELETE" }),
  renderClip: (clipId: string, render_types: string[]) =>
    request<RenderedClip[]>(`/clips/${clipId}/render`, {
      method: "POST",
      body: JSON.stringify({ render_types })
    }),
  exportEpisode: (episodeId: string) =>
    request<{ id: string; status: string; filename?: string; manifest: Record<string, unknown>; error?: string }>(
      `/episodes/${episodeId}/exports`,
      { method: "POST" }
    ),
  downloadExportUrl: (exportId: string) => `${API_BASE}${withAuthQuery(`/exports/${exportId}/download`)}`,
  downloadRenderUrl: (renderId: string) => `${API_BASE}${withAuthQuery(`/renders/${renderId}/download`)}`,
  analysisEventsUrl: (episodeId: string, since?: string) => {
    const path = since
      ? `/episodes/${episodeId}/analysis-events?since=${encodeURIComponent(since)}`
      : `/episodes/${episodeId}/analysis-events`;
    return `${API_BASE}${withAuthQuery(path)}`;
  }
};

import type { AnalysisPayload, Clip, Episode, RenderedClip } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  episodes: () => request<Episode[]>("/episodes"),
  createEpisode: (payload: Partial<Episode>) =>
    request<Episode>("/episodes", { method: "POST", body: JSON.stringify(payload) }),
  saveContext: (episodeId: string, payload: Record<string, unknown>) =>
    request(`/episodes/${episodeId}/context`, { method: "PATCH", body: JSON.stringify(payload) }),
  uploadAsset: (episodeId: string, form: FormData) =>
    request(`/episodes/${episodeId}/assets`, { method: "POST", body: form }),
  uploadTranscript: (episodeId: string, form: FormData) =>
    request(`/episodes/${episodeId}/transcript`, { method: "POST", body: form }),
  analyze: (episodeId: string, payload: AnalysisPayload) =>
    request(`/episodes/${episodeId}/analyze`, { method: "POST", body: JSON.stringify(payload) }),
  clips: (episodeId: string, filters: { clip_type?: string; status?: string }) => {
    const params = new URLSearchParams();
    if (filters.clip_type) params.set("clip_type", filters.clip_type);
    if (filters.status) params.set("status", filters.status);
    const suffix = params.toString() ? `?${params}` : "";
    return request<Clip[]>(`/episodes/${episodeId}/clips${suffix}`);
  },
  updateClipStatus: (clipId: string, status: string, comments = "") =>
    request<Clip>(`/clips/${clipId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, comments, user_name: "AURORA Demo" })
    }),
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
  downloadExportUrl: (exportId: string) => `${API_BASE}/exports/${exportId}/download`,
  downloadRenderUrl: (renderId: string) => `${API_BASE}/renders/${renderId}/download`
};

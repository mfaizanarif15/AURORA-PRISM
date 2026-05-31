export type Episode = {
  id: string;
  title: string;
  guest_name?: string | null;
  guest_role?: string | null;
  guest_company?: string | null;
  recording_date?: string | null;
  status: string;
  clip_count: number;
  asset_count: number;
  media_asset_count: number;
  transcript_segment_count: number;
};

export type ClipMetadata = {
  platform: string;
  title: string;
  hook: string;
  caption: string;
  soft_cta: string;
  business_cta: string;
  hashtags: string[];
  pinned_comment?: string | null;
  thumbnail_concepts: Array<Record<string, string>>;
  risk_flags: string[];
};

export type RenderedClip = {
  id: string;
  render_type: string;
  status: string;
  filename?: string | null;
  error?: string | null;
};

export type AnalysisRun = {
  id: string;
  episode_id: string;
  status: string;
  mode: string;
  summary?: string | null;
  generated_clip_count: number;
};

export type AnalysisEvent = {
  id: number;
  episode_id: string;
  event_type: string;
  message: string;
  level: "info" | "success" | "warning" | "error" | string;
  progress?: number | null;
  data: Record<string, unknown>;
  created_at: string;
};

export type AuthUser = {
  id: string;
  username: string;
  display_name: string;
};

export type AuthSession = {
  access_token: string;
  token_type: "bearer" | string;
  expires_at: number;
  user: AuthUser;
};

export type AuthProfilePayload = {
  username?: string;
  display_name?: string;
  current_password?: string;
  new_password?: string;
};

export type Clip = {
  id: string;
  episode_id: string;
  clip_type: "short" | "highlight";
  target_platform: string;
  purpose: string;
  moment_type: string;
  status: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  excerpt: string;
  reasoning: string;
  rank: number;
  metadata: ClipMetadata[];
  rendered_clips: RenderedClip[];
};

export type AnalysisSectionKey = "tiktok" | "instagram_reels" | "youtube_shorts" | "linkedin" | "highlights";

export type AnalysisSectionConfig = {
  enabled: boolean;
  target_count: number;
  duration_min_seconds: number | null;
  duration_max_seconds: number | null;
};

export type AnalysisPayload = {
  ai_provider: "azure_openai" | "openai";
  duration_min_seconds?: number | null;
  duration_max_seconds?: number | null;
  custom_instructions?: string | null;
  mode: "mock" | "hybrid" | "openai";
  sections: Record<AnalysisSectionKey, AnalysisSectionConfig>;
};

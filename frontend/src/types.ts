export type Episode = {
  id: string;
  title: string;
  guest_name?: string | null;
  guest_role?: string | null;
  guest_company?: string | null;
  recording_date?: string | null;
  theme?: string | null;
  status: string;
  clip_count: number;
  asset_count: number;
  media_asset_count: number;
  transcript_segment_count: number;
};

export type ClipScore = {
  total_score: number;
  icp_relevance: number;
  tkxel_alignment: number;
  hook_strength: number;
  virality_potential: number;
  business_value: number;
  guest_authority: number;
  topic_fit: number;
  audio_confidence: number;
  explanation: string;
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

export type EpisodeEvent = {
  id: number;
  episode_id: string;
  event_type: string;
  message: string;
  level: "info" | "success" | "warning" | "error" | string;
  progress?: number | null;
  data: Record<string, unknown>;
  created_at: string;
};

export type AnalysisRun = {
  id: string;
  episode_id: string;
  status: string;
  mode: string;
  summary?: string | null;
  generated_clip_count: number;
};

export type AuthUser = {
  id: string;
  username: string;
  display_name: string;
  role: string;
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
  moment_type: string;
  status: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  excerpt: string;
  reasoning: string;
  rank: number;
  score?: ClipScore | null;
  metadata: ClipMetadata[];
  rendered_clips: RenderedClip[];
};

export type AnalysisPayload = {
  ai_provider: "azure_openai" | "openai";
  clip_types: Array<"short" | "highlight">;
  duration_min_seconds?: number | null;
  duration_max_seconds?: number | null;
  target_clip_count: number;
  platforms: string[];
  custom_instructions?: string | null;
  mode: "mock" | "hybrid" | "openai";
};

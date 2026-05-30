from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EpisodeCreate(BaseModel):
    title: str = Field(default="Untitled episode", min_length=1, max_length=255)
    guest_name: str | None = None
    guest_role: str | None = None
    guest_company: str | None = None
    recording_date: str | None = None
    theme: str | None = None


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    guest_name: str | None = None
    guest_role: str | None = None
    guest_company: str | None = None
    recording_date: str | None = None
    theme: str | None = None


class EpisodeAutoTitleRequest(BaseModel):
    ai_provider: Literal["azure_openai", "openai"] = "azure_openai"


class EpisodeContextUpdate(BaseModel):
    icp: str | None = None
    target_audience: str | None = None
    audience_pain_points: str | None = None
    tkxel_services: str | None = None
    hot_topic: str | None = None
    business_objectives: str | None = None
    episode_plan: str | None = None
    preferred_platforms: list[str] = Field(default_factory=lambda: ["youtube_shorts", "linkedin", "instagram_reels", "tiktok"])
    editor_notes: str | None = None


class TranscriptIn(BaseModel):
    content: str
    source_format: str = "txt"


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class AuthSignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class AuthProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    current_password: str | None = Field(default=None, min_length=1, max_length=255)
    new_password: str | None = Field(default=None, min_length=8, max_length=255)


class AuthUserRead(BaseModel):
    id: str
    username: str
    display_name: str
    role: str


class AuthSessionRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    user: AuthUserRead


class AnalysisRequest(BaseModel):
    ai_provider: Literal["azure_openai", "openai"] = "azure_openai"
    clip_types: list[Literal["short", "highlight"]] = Field(default_factory=lambda: ["short", "highlight"])
    duration_min_seconds: int | None = None
    duration_max_seconds: int | None = None
    target_clip_count: int = Field(default=10, ge=1, le=30)
    platforms: list[str] = Field(default_factory=lambda: ["youtube_shorts", "linkedin", "instagram_reels", "tiktok"])
    custom_instructions: str | None = None
    mode: Literal["mock", "hybrid", "openai"] = "hybrid"


class ClipStatusUpdate(BaseModel):
    status: Literal["draft", "recommended", "approved", "rejected", "needs_revision", "exported"]
    user_name: str | None = "Demo Reviewer"
    comments: str | None = None


class RenderRequest(BaseModel):
    render_types: list[Literal["original", "vertical", "audio", "waveform"]] = Field(
        default_factory=lambda: ["original", "vertical"]
    )


class ScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_score: int
    icp_relevance: int
    tkxel_alignment: int
    hook_strength: int
    virality_potential: int
    business_value: int
    guest_authority: int
    topic_fit: int
    audio_confidence: int
    explanation: str


class MetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform: str
    title: str
    hook: str
    caption: str
    soft_cta: str
    business_cta: str
    hashtags: list[str]
    pinned_comment: str | None
    thumbnail_concepts: list[dict[str, Any]]
    risk_flags: list[str]


class RenderedClipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    render_type: str
    status: str
    filename: str | None
    error: str | None


class ClipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    episode_id: str
    clip_type: str
    moment_type: str
    status: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    excerpt: str
    reasoning: str
    rank: int
    score: ScoreRead | None
    metadata: list[MetadataRead]
    rendered_clips: list[RenderedClipRead]


class EpisodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    guest_name: str | None
    guest_role: str | None
    guest_company: str | None
    recording_date: str | None
    theme: str | None
    status: str
    clip_count: int = 0
    asset_count: int = 0
    media_asset_count: int = 0
    transcript_segment_count: int = 0


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_type: str
    filename: str
    content_type: str | None
    tags: list[str]
    is_primary: bool
    has_extracted_text: bool


class TranscriptUploadResult(BaseModel):
    segment_count: int
    first_timestamp: float | None
    last_timestamp: float | None


class AnalysisRunRead(BaseModel):
    id: str
    episode_id: str
    status: str
    mode: str
    summary: str | None
    generated_clip_count: int


class ExportPackRead(BaseModel):
    id: str
    status: str
    filename: str | None
    manifest: dict[str, Any]
    error: str | None


class AiProviderRead(BaseModel):
    default_provider: Literal["azure_openai", "openai"]
    providers: list[Literal["azure_openai", "openai"]]
    azure_openai_configured: bool
    openai_configured: bool

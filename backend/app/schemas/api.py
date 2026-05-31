from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EpisodeCreate(BaseModel):
    title: str = Field(default="Untitled episode", min_length=1, max_length=255)
    guest_name: str | None = None
    guest_role: str | None = None
    guest_company: str | None = None
    recording_date: str | None = None


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    guest_name: str | None = None
    guest_role: str | None = None
    guest_company: str | None = None
    recording_date: str | None = None


class EpisodeAutoTitleRequest(BaseModel):
    ai_provider: Literal["azure_openai", "openai"] = "azure_openai"


class EpisodeContextUpdate(BaseModel):
    icp: str | None = None
    target_audience: str | None = None
    audience_pain_points: str | None = None
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


class AuthSessionRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    user: AuthUserRead


ANALYSIS_SECTION_KEYS = ("tiktok", "instagram_reels", "youtube_shorts", "linkedin", "highlights")
CLIP_STATUSES = ("draft", "recommended", "approved", "rejected", "exported")
ANALYSIS_SECTION_DURATION_DEFAULTS = {
    "tiktok": (30, 60),
    "instagram_reels": (30, 75),
    "youtube_shorts": (30, 90),
    "linkedin": (45, 120),
    "highlights": (180, 360),
}


class AnalysisSectionConfig(BaseModel):
    enabled: bool = True
    target_count: int = Field(default=3, ge=1, le=10)
    duration_min_seconds: int | None = Field(default=None, ge=1, le=1800)
    duration_max_seconds: int | None = Field(default=None, ge=1, le=1800)

    @model_validator(mode="after")
    def validate_duration_range(self) -> "AnalysisSectionConfig":
        if (
            self.duration_min_seconds is not None
            and self.duration_max_seconds is not None
            and self.duration_min_seconds > self.duration_max_seconds
        ):
            raise ValueError("duration_min_seconds must be less than or equal to duration_max_seconds")
        return self


def default_analysis_sections() -> dict[str, AnalysisSectionConfig]:
    return {
        "tiktok": AnalysisSectionConfig(enabled=True, target_count=3),
        "instagram_reels": AnalysisSectionConfig(enabled=True, target_count=3),
        "youtube_shorts": AnalysisSectionConfig(enabled=True, target_count=3),
        "linkedin": AnalysisSectionConfig(enabled=True, target_count=3),
        "highlights": AnalysisSectionConfig(enabled=False, target_count=3),
    }


class AnalysisRequest(BaseModel):
    ai_provider: Literal["azure_openai", "openai"] = "azure_openai"
    clip_types: list[Literal["short", "highlight"]] = Field(default_factory=lambda: ["short", "highlight"])
    duration_min_seconds: int | None = None
    duration_max_seconds: int | None = None
    target_clip_count: int = Field(default=3, ge=1, le=10)
    platforms: list[str] = Field(default_factory=lambda: ["youtube_shorts", "linkedin", "instagram_reels", "tiktok"])
    custom_instructions: str | None = None
    mode: Literal["mock", "hybrid", "openai"] = "hybrid"
    sections: dict[str, AnalysisSectionConfig] = Field(default_factory=default_analysis_sections)

    @model_validator(mode="after")
    def normalize_sections(self) -> "AnalysisRequest":
        defaults = default_analysis_sections()
        normalized: dict[str, AnalysisSectionConfig] = {}
        for key in ANALYSIS_SECTION_KEYS:
            normalized[key] = self.sections.get(key, defaults[key])
        self.sections = normalized
        if not any(config.enabled for config in self.sections.values()):
            raise ValueError("At least one output section must be enabled")
        return self

    def enabled_sections(self) -> list[tuple[str, AnalysisSectionConfig]]:
        return [(key, config) for key, config in self.sections.items() if config.enabled]


class ClipStatusUpdate(BaseModel):
    status: Literal["draft", "recommended", "approved", "rejected", "exported"]
    user_name: str | None = "Demo Reviewer"
    comments: str | None = None


class RenderRequest(BaseModel):
    render_types: list[Literal["video", "audio"]] = Field(default_factory=list)


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
    target_platform: str
    purpose: str
    moment_type: str
    status: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    excerpt: str
    reasoning: str
    rank: int
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
    azure_openai_transcription_configured: bool
    openai_configured: bool

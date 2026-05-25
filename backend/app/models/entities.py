import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Episode(Base, TimestampMixin):
    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    guest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recording_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="draft")

    context: Mapped["EpisodeContext | None"] = relationship(
        back_populates="episode", cascade="all, delete-orphan", uselist=False
    )
    assets: Mapped[list["Asset"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan", order_by="TranscriptSegment.start_seconds"
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    clips: Mapped[list["ClipCandidate"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportPack"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class EpisodeContext(Base, TimestampMixin):
    __tablename__ = "episode_contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), unique=True)
    icp: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    tkxel_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    hot_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_objectives: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    editor_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="context")


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    episode: Mapped[Episode] = relationship(back_populates="assets")


class TranscriptSegment(Base, TimestampMixin):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="transcript_segments")


class AnalysisRun(Base, TimestampMixin):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(64), default="mock")
    status: Mapped[str] = mapped_column(String(64), default="running")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="analysis_runs")
    clips: Mapped[list["ClipCandidate"]] = relationship(back_populates="analysis_run")


class ClipCandidate(Base, TimestampMixin):
    __tablename__ = "clip_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    clip_type: Mapped[str] = mapped_column(String(64))
    moment_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64), default="recommended")
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[float] = mapped_column(Float)
    excerpt: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    episode: Mapped[Episode] = relationship(back_populates="clips")
    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="clips")
    score: Mapped["ClipScore | None"] = relationship(
        back_populates="clip", cascade="all, delete-orphan", uselist=False
    )
    metadata_items: Mapped[list["ClipMetadata"]] = relationship(
        back_populates="clip", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ApprovalEvent"]] = relationship(
        back_populates="clip", cascade="all, delete-orphan"
    )
    rendered_clips: Mapped[list["RenderedClip"]] = relationship(
        back_populates="clip", cascade="all, delete-orphan"
    )


class ClipScore(Base, TimestampMixin):
    __tablename__ = "clip_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clip_candidates.id", ondelete="CASCADE"), unique=True)
    total_score: Mapped[int] = mapped_column(Integer)
    icp_relevance: Mapped[int] = mapped_column(Integer)
    tkxel_alignment: Mapped[int] = mapped_column(Integer)
    hook_strength: Mapped[int] = mapped_column(Integer)
    virality_potential: Mapped[int] = mapped_column(Integer)
    business_value: Mapped[int] = mapped_column(Integer)
    guest_authority: Mapped[int] = mapped_column(Integer)
    topic_fit: Mapped[int] = mapped_column(Integer)
    audio_confidence: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)

    clip: Mapped[ClipCandidate] = relationship(back_populates="score")


class ClipMetadata(Base, TimestampMixin):
    __tablename__ = "clip_metadata"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clip_candidates.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    hook: Mapped[str] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text)
    soft_cta: Mapped[str] = mapped_column(Text)
    business_cta: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    pinned_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_concepts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)

    clip: Mapped[ClipCandidate] = relationship(back_populates="metadata_items")


class ApprovalEvent(Base, TimestampMixin):
    __tablename__ = "approval_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clip_candidates.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    clip: Mapped[ClipCandidate] = relationship(back_populates="approvals")


class RenderedClip(Base, TimestampMixin):
    __tablename__ = "rendered_clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clip_candidates.id", ondelete="CASCADE"))
    render_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="pending")
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    clip: Mapped[ClipCandidate] = relationship(back_populates="rendered_clips")


class ExportPack(Base, TimestampMixin):
    __tablename__ = "export_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(64), default="pending")
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="exports")

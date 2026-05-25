"""initial schema

Revision ID: 20260522_0001
Revises:
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("guest_name", sa.String(length=255), nullable=True),
        sa.Column("guest_role", sa.String(length=255), nullable=True),
        sa.Column("guest_company", sa.String(length=255), nullable=True),
        sa.Column("recording_date", sa.String(length=64), nullable=True),
        sa.Column("theme", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "episode_contexts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("icp", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("audience_pain_points", sa.Text(), nullable=True),
        sa.Column("tkxel_services", sa.Text(), nullable=True),
        sa.Column("hot_topic", sa.Text(), nullable=True),
        sa.Column("business_objectives", sa.Text(), nullable=True),
        sa.Column("episode_plan", sa.Text(), nullable=True),
        sa.Column("preferred_platforms", sa.JSON(), nullable=False),
        sa.Column("editor_notes", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("episode_id"),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "clip_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_run_id", sa.String(length=36), nullable=False),
        sa.Column("clip_type", sa.String(length=64), nullable=False),
        sa.Column("moment_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "clip_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("icp_relevance", sa.Integer(), nullable=False),
        sa.Column("tkxel_alignment", sa.Integer(), nullable=False),
        sa.Column("hook_strength", sa.Integer(), nullable=False),
        sa.Column("virality_potential", sa.Integer(), nullable=False),
        sa.Column("business_value", sa.Integer(), nullable=False),
        sa.Column("guest_authority", sa.Integer(), nullable=False),
        sa.Column("topic_fit", sa.Integer(), nullable=False),
        sa.Column("audio_confidence", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["clip_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_id"),
    )
    op.create_table(
        "clip_metadata",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("soft_cta", sa.Text(), nullable=False),
        sa.Column("business_cta", sa.Text(), nullable=False),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("pinned_comment", sa.Text(), nullable=True),
        sa.Column("thumbnail_concepts", sa.JSON(), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["clip_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "approval_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["clip_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rendered_clips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("render_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["clip_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "export_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_episode_type", "assets", ["episode_id", "asset_type"])
    op.create_index("ix_clips_episode_status", "clip_candidates", ["episode_id", "status"])
    op.create_index("ix_transcript_episode_start", "transcript_segments", ["episode_id", "start_seconds"])


def downgrade() -> None:
    op.drop_index("ix_transcript_episode_start", table_name="transcript_segments")
    op.drop_index("ix_clips_episode_status", table_name="clip_candidates")
    op.drop_index("ix_assets_episode_type", table_name="assets")
    op.drop_table("export_packs")
    op.drop_table("rendered_clips")
    op.drop_table("approval_events")
    op.drop_table("clip_metadata")
    op.drop_table("clip_scores")
    op.drop_table("clip_candidates")
    op.drop_table("analysis_runs")
    op.drop_table("transcript_segments")
    op.drop_table("assets")
    op.drop_table("episode_contexts")
    op.drop_table("episodes")

# AURORA PRISM Database Tables

This project uses PostgreSQL for the main application database.

## Connection

Local `.env` connection string:

```text
DATABASE_URL=postgresql+asyncpg://aurora:aurora@localhost:55433/aurora_prism
```

pgAdmin connection fields:

| Field | Value |
| --- | --- |
| Host name/address | `localhost` |
| Port | `55433` |
| Maintenance database | `aurora_prism` |
| Username | `aurora` |
| Password | `aurora` |

Docker backend connection:

```text
postgresql+asyncpg://aurora:aurora@postgres:5432/aurora_prism
```

The app schema is defined in `backend/app/models/entities.py` and created by Alembic migrations in `backend/alembic/versions/`.

## Table Count

The main app database has 12 application tables.

| # | Table | Purpose |
| --- | --- | --- |
| 1 | `users` | Stores sign-up/login users and password hashes. |
| 2 | `episodes` | Stores podcast episode records and workflow status. |
| 3 | `episode_contexts` | Stores ICP, target audience, business objectives, and editorial context for one episode. |
| 4 | `assets` | Stores uploaded media, documents, brand references, paths, and extracted text. |
| 5 | `transcript_segments` | Stores timestamped transcript rows for an episode. |
| 6 | `analysis_runs` | Stores each clip analysis request, mode, status, summary, and errors. |
| 7 | `clip_candidates` | Stores recommended clip windows, timing, ranking, status, excerpt, and reasoning. |
| 8 | `clip_scores` | Stores one score breakdown for each clip candidate. |
| 9 | `clip_metadata` | Stores platform-specific titles, hooks, captions, CTAs, hashtags, and risk flags for clips. |
| 10 | `approval_events` | Stores clip review actions such as approved, rejected, or needs revision. |
| 11 | `rendered_clips` | Stores render output records, file paths, filenames, status, and errors. |
| 12 | `export_packs` | Stores export ZIP handoff packages and manifests. |

## Tables

### `users`

Application users for sign up and login.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `username` | `String(255)` | Unique normalized username. |
| `display_name` | `String(255)` | User-facing name. |
| `role` | `String(64)` | User role, default `Content Operations`. |
| `password_hash` | `Text` | PBKDF2-SHA256 password hash. |
| `is_active` | `Boolean` | Whether the user can sign in. |
| `last_login_at` | `DateTime(timezone=True)` | Last successful login timestamp. |
| `created_at` | `DateTime(timezone=True)` | Created timestamp. |
| `updated_at` | `DateTime(timezone=True)` | Updated timestamp. |

Indexes:

- `ix_users_username` on `username`.

### `episodes`

Primary episode entity.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `owner_user_id` | `String(36)` | Optional foreign key to `users.id`; controls which logged-in user can see the episode and its history. |
| `title` | `String(255)` | Episode title. |
| `guest_name` | `String(255)` | Optional guest name. |
| `guest_role` | `String(255)` | Optional guest role. |
| `guest_company` | `String(255)` | Optional guest company. |
| `recording_date` | `String(64)` | Optional recording date. |
| `theme` | `String(255)` | Optional episode theme. |
| `status` | `String(64)` | Episode workflow status, default `draft`. |
| `created_at` | `DateTime(timezone=True)` | Created timestamp. |
| `updated_at` | `DateTime(timezone=True)` | Updated timestamp. |

Relationships:

- Belongs to one `users` row through `owner_user_id` when assigned.
- One episode has one `episode_contexts` row.
- One episode has many `assets`, `transcript_segments`, `analysis_runs`, `clip_candidates`, and `export_packs`.

Indexes:

- `ix_episodes_owner_user_id` on `owner_user_id`.

### `episode_contexts`

Episode strategy and editorial context.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Unique foreign key to `episodes.id`. |
| `icp` | `Text` | Ideal customer profile. |
| `target_audience` | `Text` | Target audience description. |
| `audience_pain_points` | `Text` | Audience pain points. |
| `tkxel_services` | `Text` | Relevant TKXEL services. |
| `hot_topic` | `Text` | Main hot topic. |
| `business_objectives` | `Text` | Business goals for the episode. |
| `episode_plan` | `Text` | Optional editorial plan. |
| `preferred_platforms` | `JSON` | Preferred output platforms. |
| `editor_notes` | `Text` | Notes for clip selection and metadata. |

Relationship:

- Belongs to one `episodes` row.

### `assets`

Uploaded episode files.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Foreign key to `episodes.id`. |
| `asset_type` | `String(64)` | Example: `video`, `audio`, `guest_document`, `guest_headshot`, `brand_reference`. |
| `filename` | `String(512)` | Original or saved filename. |
| `content_type` | `String(255)` | MIME type when available. |
| `path` | `Text` | Storage path. |
| `extracted_text` | `Text` | Extracted document text when available. |
| `tags` | `JSON` | Tags list. |
| `is_primary` | `Boolean` | Marks primary video/audio asset. |

Indexes:

- `ix_assets_episode_type` on `episode_id`, `asset_type`.

### `transcript_segments`

Timestamped transcript content.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Foreign key to `episodes.id`. |
| `speaker` | `String(255)` | Optional speaker label. |
| `start_seconds` | `Float` | Segment start time. |
| `end_seconds` | `Float` | Segment end time. |
| `text` | `Text` | Transcript text. |
| `confidence` | `Float` | Optional confidence score. |

Indexes:

- `ix_transcript_episode_start` on `episode_id`, `start_seconds`.

### `analysis_runs`

Analysis execution records.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Foreign key to `episodes.id`. |
| `mode` | `String(64)` | `mock`, `hybrid`, or `openai`. |
| `status` | `String(64)` | Default `running`; can become `completed` or `failed`. |
| `request` | `JSON` | Original analysis request payload. |
| `summary` | `Text` | Optional run summary. |
| `error` | `Text` | Optional failure details. |

Relationships:

- Belongs to one `episodes` row.
- Has many `clip_candidates`.

### `clip_candidates`

Generated clip recommendations.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Foreign key to `episodes.id`. |
| `analysis_run_id` | `String(36)` | Foreign key to `analysis_runs.id`. |
| `clip_type` | `String(64)` | `short` or `highlight`. |
| `moment_type` | `String(128)` | Moment category. |
| `status` | `String(64)` | Default `recommended`; can be approved, rejected, etc. |
| `start_seconds` | `Float` | Clip start time. |
| `end_seconds` | `Float` | Clip end time. |
| `duration_seconds` | `Float` | Clip duration. |
| `excerpt` | `Text` | Transcript excerpt. |
| `reasoning` | `Text` | Why the clip was selected. |
| `rank` | `Integer` | Ranking within the run. |

Relationships:

- Has one `clip_scores` row.
- Has many `clip_metadata`, `approval_events`, and `rendered_clips`.

Indexes:

- `ix_clips_episode_status` on `episode_id`, `status`.

### `clip_scores`

Score breakdown for a clip candidate.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `clip_id` | `String(36)` | Unique foreign key to `clip_candidates.id`. |
| `total_score` | `Integer` | Overall score. |
| `icp_relevance` | `Integer` | ICP relevance score. |
| `tkxel_alignment` | `Integer` | TKXEL alignment score. |
| `hook_strength` | `Integer` | Hook strength score. |
| `virality_potential` | `Integer` | Virality potential score. |
| `business_value` | `Integer` | Business value score. |
| `guest_authority` | `Integer` | Guest authority score. |
| `topic_fit` | `Integer` | Topic fit score. |
| `audio_confidence` | `Integer` | Audio confidence score. |
| `explanation` | `Text` | Score explanation. |

Relationship:

- Belongs to one `clip_candidates` row.

### `clip_metadata`

Platform-specific publishing metadata for clip candidates.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `clip_id` | `String(36)` | Foreign key to `clip_candidates.id`. |
| `platform` | `String(64)` | Example: `youtube_shorts`, `tiktok`, `instagram_reels`, `linkedin`. |
| `title` | `String(255)` | Platform title. |
| `hook` | `Text` | Opening hook. |
| `caption` | `Text` | Post caption. |
| `soft_cta` | `Text` | Soft call-to-action. |
| `business_cta` | `Text` | Business call-to-action. |
| `hashtags` | `JSON` | Hashtag list. |
| `pinned_comment` | `Text` | Optional pinned comment. |
| `thumbnail_concepts` | `JSON` | Thumbnail ideas. |
| `risk_flags` | `JSON` | Risk flags list. |

Relationship:

- Belongs to one `clip_candidates` row.

### `approval_events`

Clip review/audit actions.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `clip_id` | `String(36)` | Foreign key to `clip_candidates.id`. |
| `status` | `String(64)` | Review status applied to the clip. |
| `user_name` | `String(255)` | Optional reviewer name. |
| `comments` | `Text` | Optional review comments. |

Relationship:

- Belongs to one `clip_candidates` row.

### `rendered_clips`

Render job/output records.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `clip_id` | `String(36)` | Foreign key to `clip_candidates.id`. |
| `render_type` | `String(64)` | `original`, `vertical`, `audio`, or `waveform`. |
| `status` | `String(64)` | Default `pending`; can become `running`, `completed`, or `failed`. |
| `path` | `Text` | Optional rendered file path. |
| `filename` | `String(512)` | Optional rendered filename. |
| `error` | `Text` | Optional render error. |

Relationship:

- Belongs to one `clip_candidates` row.

### `export_packs`

Export ZIP package records.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `String(36)` | Primary key UUID string. |
| `episode_id` | `String(36)` | Foreign key to `episodes.id`. |
| `status` | `String(64)` | Default `pending`; can become `running`, `completed`, or `failed`. |
| `path` | `Text` | Optional ZIP file path. |
| `filename` | `String(512)` | Optional ZIP filename. |
| `manifest` | `JSON` | Export manifest payload. |
| `error` | `Text` | Optional export error. |

Relationship:

- Belongs to one `episodes` row.

## Notes

- Authentication is database-backed with the `users` table. Tokens are signed server-side and can be revoked in-process on logout.
- If the `users` table is empty, the first successful login with the configured local admin credentials can bootstrap the initial admin user.
- Episode history is user-scoped through `episodes.owner_user_id`. Authenticated users only list or access episodes they own, and child resources are checked through that episode ownership.
- The ownership migration assigns legacy episodes to the first existing user if a user exists; otherwise they stay unassigned until updated.
- The optional Langfuse profile in Docker Compose has its own separate database containers and is not part of the AURORA PRISM application schema.
- Files themselves are stored on disk under `STORAGE_ROOT`; the database stores paths and metadata.

# AURORA PRISM API Reference

Backend base URL for Docker:

```text
http://localhost:8100/api
```

Interactive OpenAPI docs:

```text
http://localhost:8100/docs
```

Database schema and table details are documented in [DATABASE_TABLES.md](DATABASE_TABLES.md).

Authentication is enabled by default. Call `POST /auth/login` and send the returned bearer token as:

```text
Authorization: Bearer <access_token>
```

For browser download URLs that cannot attach custom headers, the frontend appends `?token=<access_token>`.

The app supports database-backed sign up and login. If the `users` table is empty, these configured local credentials can bootstrap the first user:

```text
Username: admin
Password: aurora-admin
```

All endpoints return JSON unless the endpoint name says `download`.

## Authentication

### POST `/auth/signup`

Creates a database-backed user and returns a bearer session.

Input JSON:

```json
{
  "username": "operator",
  "display_name": "AURORA Operator",
  "password": "strong-password"
}
```

Output:

```json
{
  "access_token": "signed-session-token",
  "token_type": "bearer",
  "expires_at": 1790000000,
  "user": {
    "id": "user-uuid",
    "username": "operator",
    "display_name": "AURORA Operator"
  }
}
```

### POST `/auth/login`

Input JSON:

```json
{
  "username": "admin",
  "password": "aurora-admin"
}
```

Output:

```json
{
  "access_token": "signed-session-token",
  "token_type": "bearer",
  "expires_at": 1790000000,
  "user": {
    "id": "user-uuid",
    "username": "admin",
    "display_name": "AURORA Operator"
  }
}
```

### GET `/auth/me`

Returns the current authenticated user.

### PATCH `/auth/me`

Updates the current user's profile and optionally changes password. Returns a fresh bearer session.

Input JSON:

```json
{
  "username": "operator",
  "display_name": "AURORA Operator",
  "current_password": "old-password",
  "new_password": "new-password"
}
```

For profile-only changes, omit `current_password` and `new_password`. Password changes require the current password.

Output:

```json
{
  "access_token": "new-signed-session-token",
  "token_type": "bearer",
  "expires_at": 1790000000,
  "user": {
    "id": "user-uuid",
    "username": "operator",
    "display_name": "AURORA Operator"
  }
}
```

### POST `/auth/logout`

Returns `{ "status": "ok" }`. The backend revokes the current token for the running process and the browser clears its stored session token.

## Common Values

Clip types:

```json
["short", "highlight"]
```

Clip statuses:

```json
["draft", "recommended", "approved", "rejected", "exported"]
```

Output section keys:

```json
["tiktok", "instagram_reels", "youtube_shorts", "linkedin", "highlights"]
```

Metadata platforms:

```json
["youtube_shorts", "tiktok", "instagram_reels", "linkedin", "generic"]
```

Render types:

```json
["video", "audio"]
```

AI providers:

```json
["azure_openai", "openai"]
```

Analysis modes:

```json
["mock", "hybrid", "openai"]
```

## Response Models

### EpisodeRead

```json
{
  "id": "uuid",
  "title": "Episode title",
  "guest_name": "Dr. Seth Dobrin",
  "guest_role": "Founder and CEO",
  "guest_company": "Qantm AI",
  "recording_date": "2024-11-25",
  "status": "draft",
  "clip_count": 0,
  "asset_count": 0,
  "media_asset_count": 0,
  "transcript_segment_count": 0
}
```

### AssetRead

```json
{
  "id": "uuid",
  "asset_type": "video",
  "filename": "episode.mp4",
  "content_type": "video/mp4",
  "tags": ["demo"],
  "is_primary": true,
  "has_extracted_text": false
}
```

### ClipRead

```json
{
  "id": "uuid",
  "episode_id": "uuid",
  "clip_type": "short",
  "target_platform": "youtube_shorts",
  "purpose": "YouTube Shorts",
  "moment_type": "expert_insight",
  "status": "recommended",
  "start_seconds": 246.0,
  "end_seconds": 318.0,
  "duration_seconds": 72.0,
  "excerpt": "Transcript excerpt...",
  "reasoning": "Why this clip matters...",
  "rank": 1,
  "metadata": [
    {
      "platform": "youtube_shorts",
      "title": "A sharp BetterTech insight on AI strategy",
      "hook": "What if the strongest moment...",
      "caption": "Caption text...",
      "soft_cta": "Watch the full BetterTech conversation...",
      "business_cta": "Talk to TKXEL...",
      "hashtags": ["#BetterTech", "#AI"],
      "pinned_comment": "Which part should leaders debate next?",
      "thumbnail_concepts": [
        {
          "headline": "A sharp BetterTech insight",
          "layout": "Guest headshot left..."
        }
      ],
      "risk_flags": []
    }
  ],
  "rendered_clips": [
    {
      "id": "uuid",
      "render_type": "video",
      "status": "completed",
      "filename": "01-short-video-246.mp4",
      "error": null
    }
  ]
}
```

## System And Observability

### GET `/health`

Checks whether the backend is running.

Input: none

Output:

```json
{
  "status": "ok"
}
```

Example:

```bash
curl http://localhost:8100/api/health
```

### GET `/ai/providers`

Returns configured AI provider status.

Input: none

Output:

```json
{
  "default_provider": "azure_openai",
  "providers": ["azure_openai", "openai"],
  "azure_openai_configured": true,
  "azure_openai_transcription_configured": false,
  "openai_configured": false
}
```

### GET `/observability/langfuse`

Returns Langfuse observability status.

Input: none

Output:

```json
{
  "enabled": true,
  "configured": true,
  "sdk_available": true,
  "base_url": "http://langfuse-web:3000",
  "environment": "local",
  "release": "aurora-prism-mvp",
  "capture_llm_io": true,
  "max_llm_io_chars": 250000
}
```

LLM-backed analysis creates a Langfuse generation named `llm_clip_analysis`. When `capture_llm_io` is true, the generation input includes the exact system/user messages and prompt payload, and the output includes the raw assistant JSON, parsed JSON, normalized clips, token usage, retry metadata, provider, model, and prompt version.

## Episodes

### GET `/episodes`

Lists the authenticated user's episodes, newest first. Other users' episode history is hidden.

Input: none

Output:

```json
[
  {
    "id": "uuid",
    "title": "Episode title",
    "guest_name": "Guest name",
    "guest_role": "Guest role",
    "guest_company": "Guest company",
    "recording_date": "2024-11-25",
    "status": "analyzed",
    "clip_count": 10,
    "asset_count": 4,
    "media_asset_count": 2,
    "transcript_segment_count": 603
  }
]
```

### POST `/episodes`

Creates a new episode owned by the authenticated user. Status defaults to `draft`. If no title is supplied, the API uses `Untitled episode` so the UI can create a workspace first and name it later.

Input JSON:

```json
{
  "title": "Dr. Seth Dobrin - Preventing Global Tech Homogenization",
  "guest_name": "Dr. Seth Dobrin",
  "guest_role": "Founder and CEO",
  "guest_company": "Qantm AI",
  "recording_date": "2024-11-25"
}
```

Required fields: none

Output: `EpisodeRead`

Example:

```bash
curl -X POST http://localhost:8100/api/episodes \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo Episode","guest_name":"Demo Guest"}'
```

### GET `/episodes/{episode_id}`

Fetches one episode by ID.

Path params:

- `episode_id`: episode UUID

Output: `EpisodeRead`

Errors:

- `404` if the episode does not exist

### PATCH `/episodes/{episode_id}`

Updates editable episode details. This is used by the episode details dialog for renaming and profile context changes.

Path params:

- `episode_id`: episode UUID

Input JSON:

```json
{
  "title": "Enterprise AI Governance with Dr. Seth Dobrin",
  "guest_name": "Dr. Seth Dobrin",
  "guest_role": "Founder and CEO",
  "guest_company": "Qantm AI",
  "recording_date": "2024-11-25"
}
```

All fields are optional. Blank optional fields are stored as `null`; a blank title becomes `Untitled episode`.

Output: `EpisodeRead`

Errors:

- `404` if the episode does not exist or does not belong to the authenticated user

### POST `/episodes/{episode_id}/auto-title`

Generates and saves a concise episode title from the episode metadata, context, and transcript excerpt. The frontend uses this endpoint from Episode details and automatically after analysis when the episode is still named `Untitled episode`. If the configured LLM provider is unavailable, the API falls back to a local title heuristic.

Path params:

- `episode_id`: episode UUID

Input JSON:

```json
{
  "ai_provider": "azure_openai"
}
```

Output: `EpisodeRead`

Errors:

- `404` if the episode does not exist or does not belong to the authenticated user

### DELETE `/episodes/{episode_id}`

Deletes one owned episode from history. Child records such as context, assets, transcript segments, analysis runs, clips, rendered clips, approval events, and export packs are removed through episode cascades.

Path params:

- `episode_id`: episode UUID

Output:

```json
{
  "status": "deleted",
  "episode_id": "uuid"
}
```

Errors:

- `404` if the episode does not exist or does not belong to the authenticated user

### PATCH `/episodes/{episode_id}/context`

Creates or updates business/editorial context for an episode.

Path params:

- `episode_id`: episode UUID

Input JSON:

```json
{
  "icp": "B2B technology leaders and enterprise product teams",
  "target_audience": "Executives evaluating AI strategy",
  "audience_pain_points": "AI risk, unclear ROI, implementation cost",
  "hot_topic": "AI governance and business impact",
  "business_objectives": "Grow BetterTech audience and create qualified conversations",
  "episode_plan": "Find strong shorts and deeper highlights",
  "preferred_platforms": ["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
  "editor_notes": "Keep claims credible and specific."
}
```

All fields are optional, but useful analysis requires business context.

Output:

```json
{
  "status": "saved",
  "episode_id": "uuid"
}
```

Errors:

- `404` if the episode does not exist

## Assets And Transcript

### POST `/episodes/{episode_id}/assets`

Uploads a media file, document, image, or brand reference.

Content type:

```text
multipart/form-data
```

Form fields:

- `file`: uploaded file, required
- `asset_type`: string, required
- `tags`: comma-separated tags, optional
- `is_primary`: boolean, optional, default `false`

Recommended `asset_type` values:

```json
["video", "audio", "guest_document", "guest_headshot", "brand_reference"]
```

Supported examples:

- Video: MP4/MOV
- Audio: WAV/MP3/M4A
- Transcript/supporting docs: TXT/PDF/DOCX/CSV/VTT/SRT
- Images: PNG/JPG/WebP

PDF, DOCX, TXT, Markdown, CSV, VTT, and SRT uploads are parsed into `assets.extracted_text`.
Parsed `guest_document`, `brand_reference`, `document`, and `supporting_document` assets are included as supporting context during analysis.

Output: `AssetRead`

Example:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/assets \
  -F "asset_type=video" \
  -F "is_primary=true" \
  -F "file=@episode.mp4"
```

Errors:

- `404` if the episode does not exist

### POST `/episodes/{episode_id}/transcript`

Uploads, pastes, or transcribes a transcript source. Existing transcript segments for the episode are replaced after a transcript is parsed successfully. If audio transcription is skipped because no transcription provider is configured, the uploaded audio asset is saved and existing transcript segments are left unchanged.

Content type:

```text
multipart/form-data
```

Option A input fields:

- `file`: transcript document file or transcribable audio/video file
- `source_format`: optional, one of `txt`, `md`, `vtt`, `srt`, `csv`, `pdf`, `docx`; ignored for audio/video files

Supported transcript document files:

- `txt`, `md`, `vtt`, `srt`, `csv`, `pdf`, `docx`
- PDF/DOCX transcript files are stored as `transcript_source` assets and parsed into transcript segments

Supported audio/video transcript files:

- `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, `webm`
- Uses standard OpenAI Whisper when `OPENAI_API_KEY` is set
- Falls back to Azure transcription when `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT`, Azure endpoint, and Azure key are configured
- Skips transcription and returns zero segments when neither transcription provider is configured

Option B input fields:

- `content`: pasted transcript text
- `source_format`: optional, default `txt`

Output:

```json
{
  "segment_count": 603,
  "first_timestamp": 2.053,
  "last_timestamp": 3588.2
}
```

Skipped audio transcription output:

```json
{
  "segment_count": 0,
  "first_timestamp": null,
  "last_timestamp": null
}
```

Example with file:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/transcript \
  -F "source_format=txt" \
  -F "file=@seth-dobrin-bt-podcast.txt"
```

Example with audio:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/transcript \
  -F "file=@episode-audio.mp3"
```

Example with pasted content:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/transcript \
  -F "source_format=txt" \
  -F "content=Speaker (00:01.000)
This is the transcript text."
```

Errors:

- `400` if neither `file` nor `content` is provided
- `400` if transcription runs but produces no transcript text or fails
- `404` if the episode does not exist

## Analysis

### POST `/episodes/{episode_id}/analyze`

Runs section-specific output analysis for an episode. A transcript must already exist.

Path params:

- `episode_id`: episode UUID

Input JSON:

```json
{
  "ai_provider": "azure_openai",
  "duration_min_seconds": null,
  "duration_max_seconds": null,
  "custom_instructions": "Focus on AI governance and avoid salesy outputs.",
  "mode": "hybrid",
  "sections": {
    "tiktok": { "enabled": true, "target_count": 3, "duration_min_seconds": 30, "duration_max_seconds": 60 },
    "instagram_reels": { "enabled": true, "target_count": 3, "duration_min_seconds": 30, "duration_max_seconds": 75 },
    "youtube_shorts": { "enabled": true, "target_count": 3, "duration_min_seconds": 30, "duration_max_seconds": 90 },
    "linkedin": { "enabled": true, "target_count": 3, "duration_min_seconds": 45, "duration_max_seconds": 120 },
    "highlights": { "enabled": false, "target_count": 3, "duration_min_seconds": 180, "duration_max_seconds": 360 }
  }
}
```

Field notes:

- `ai_provider`: defaults to `azure_openai`; section analysis uses Azure OpenAI
- `sections`: enabled output sections, per-section target counts, and optional per-section duration ranges
- `sections.*.duration_min_seconds` and `sections.*.duration_max_seconds`: custom timing for that section, in seconds
- top-level `duration_min_seconds` and `duration_max_seconds`: legacy override used when per-section durations are omitted
- `target_count`: 1 to 10 per section; defaults to 3
- `mode`: `mock` uses local heuristics only, `hybrid` uses the LLM with heuristic fallback, and `openai` requires a provider-backed LLM call

Default durations:

- TikTok: 30-60 seconds
- Reels: 30-75 seconds
- YouTube Shorts: 30-90 seconds
- LinkedIn: 45-120 seconds
- Highlights: 180-360 seconds

Output:

```json
{
  "id": "analysis-run-uuid",
  "episode_id": "episode-uuid",
  "status": "completed",
  "mode": "hybrid",
  "summary": "Generated 12 section outputs across tiktok, instagram_reels, youtube_shorts, linkedin using langgraph_azure(...).",
  "generated_clip_count": 12
}
```

Errors:

- `400` if transcript is missing or the episode does not exist

## Clips

### GET `/episodes/{episode_id}/clips`

Lists section outputs for an episode.

Path params:

- `episode_id`: episode UUID

Query params:

- `clip_type`: optional, `short` or `highlight`
- `target_platform`: optional section key such as `tiktok`, `instagram_reels`, `youtube_shorts`, `linkedin`, or `generic`
- `status`: optional output status

Output:

```json
[
  {
    "id": "clip-uuid",
    "episode_id": "episode-uuid",
    "clip_type": "short",
    "target_platform": "tiktok",
    "purpose": "TikTok",
    "moment_type": "hot_take",
    "status": "recommended",
    "start_seconds": 246.0,
    "end_seconds": 318.0,
    "duration_seconds": 72.0,
    "excerpt": "Transcript excerpt...",
    "reasoning": "Why this clip matters...",
    "rank": 1,
    "metadata": [],
    "rendered_clips": []
  }
]
```

Example:

```bash
curl "http://localhost:8100/api/episodes/{episode_id}/clips?clip_type=short&status=recommended"
```

### GET `/clips/{clip_id}`

Fetches one clip recommendation with metadata and rendered outputs.

Path params:

- `clip_id`: clip UUID

Output: `ClipRead`

Errors:

- `404` if the clip does not exist

### PATCH `/clips/{clip_id}/status`

Approves or rejects a clip. Also creates an approval event.

Path params:

- `clip_id`: clip UUID

Input JSON:

```json
{
  "status": "approved",
  "user_name": "Demo Reviewer",
  "comments": "Strong hook for LinkedIn and Shorts."
}
```

Output: `ClipRead`

Errors:

- `404` if the clip does not exist

## Rendering

### POST `/clips/{clip_id}/render`

Renders draft media for a clip using FFmpeg.

Path params:

- `clip_id`: clip UUID

Input JSON:

```json
{
  "render_types": ["video", "audio"]
}
```

Behavior:

- `video` creates an MP4 clip from the uploaded source video.
- `audio` creates an audio-only file from the uploaded source audio or video.

Output:

```json
[
  {
    "id": "render-uuid",
    "render_type": "video",
    "status": "completed",
    "filename": "01-short-video-246.mp4",
    "error": null
  }
]
```

Errors:

- `400` if no compatible media asset exists or FFmpeg is unavailable
- `404` if the clip does not exist

### GET `/renders/{render_id}/download`

Downloads one rendered clip file.

Path params:

- `render_id`: rendered clip UUID

Output:

- File download response

Errors:

- `404` if the rendered clip or file does not exist

## Export Packs

### POST `/episodes/{episode_id}/exports`

Creates a ZIP handoff package for approved outputs. If no outputs are approved, the current implementation falls back to the top five outputs.

Path params:

- `episode_id`: episode UUID

Input: none

Output:

```json
{
  "id": "export-pack-uuid",
  "status": "completed",
  "filename": "Episode-title-handoff.zip",
  "manifest": {
    "episode_id": "episode-uuid",
    "title": "Episode title",
    "clip_count": 5,
    "clips": [
      {
        "id": "clip-uuid",
        "clip_type": "short",
        "start": "04:06.000",
        "end": "05:18.000"
      }
    ]
  },
  "error": null
}
```

Package contents:

- Approved or fallback media files
- `handoff.md`
- `handoff.pdf`
- `handoff.docx`
- `clips.csv`
- Metadata, transcript excerpts, reasoning, titles, captions, CTAs, and thumbnail concepts

Errors:

- `404` if the episode does not exist

### GET `/exports/{export_id}/download`

Downloads one export ZIP.

Path params:

- `export_id`: export pack UUID

Output:

- File download response

Errors:

- `404` if the export pack or ZIP file does not exist

## Typical End-To-End Flow

1. Create episode:

```bash
curl -X POST http://localhost:8100/api/episodes \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo Episode","guest_name":"Demo Guest"}'
```

2. Save context:

```bash
curl -X PATCH http://localhost:8100/api/episodes/{episode_id}/context \
  -H "Content-Type: application/json" \
  -d '{"icp":"B2B tech leaders","hot_topic":"AI strategy"}'
```

3. Upload media asset:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/assets \
  -F "asset_type=video" \
  -F "is_primary=true" \
  -F "file=@episode.mp4"
```

4. Upload transcript:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/transcript \
  -F "file=@transcript.txt"
```

5. Analyze:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/analyze \
  -H "Content-Type: application/json" \
  -d '{"ai_provider":"azure_openai","mode":"hybrid","sections":{"tiktok":{"enabled":true,"target_count":3,"duration_min_seconds":30,"duration_max_seconds":60},"instagram_reels":{"enabled":true,"target_count":3,"duration_min_seconds":30,"duration_max_seconds":75},"youtube_shorts":{"enabled":true,"target_count":3,"duration_min_seconds":30,"duration_max_seconds":90},"linkedin":{"enabled":true,"target_count":3,"duration_min_seconds":45,"duration_max_seconds":120},"highlights":{"enabled":false,"target_count":3,"duration_min_seconds":180,"duration_max_seconds":360}}}'
```

6. Approve an output:

```bash
curl -X PATCH http://localhost:8100/api/clips/{clip_id}/status \
  -H "Content-Type: application/json" \
  -d '{"status":"approved","user_name":"Demo Reviewer","comments":"Approved for export."}'
```

7. Render output:

```bash
curl -X POST http://localhost:8100/api/clips/{clip_id}/render \
  -H "Content-Type: application/json" \
  -d '{"render_types":["video","audio"]}'
```

8. Create export:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/exports
```

9. Download export:

```bash
curl -L http://localhost:8100/api/exports/{export_id}/download -o handoff.zip
```

## Error Format

FastAPI returns validation and API errors in this general format:

```json
{
  "detail": "Episode not found"
}
```

Validation errors may return an array under `detail` with field-specific messages.

# AURORA PRISM API Reference

Backend base URL for Docker:

```text
http://localhost:8100/api
```

Interactive OpenAPI docs:

```text
http://localhost:8100/docs
```

The MVP currently has no authentication layer. All endpoints return JSON unless the endpoint name says `download`.

## Common Values

Clip types:

```json
["short", "highlight"]
```

Clip statuses:

```json
["draft", "recommended", "approved", "rejected", "needs_revision", "exported"]
```

Platforms:

```json
["youtube_shorts", "tiktok", "instagram_reels", "linkedin"]
```

Render types:

```json
["original", "vertical", "audio", "waveform"]
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
  "theme": "Preventing Global Tech Homogenization",
  "status": "draft",
  "clip_count": 0,
  "asset_count": 0,
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
  "moment_type": "expert_insight",
  "status": "recommended",
  "start_seconds": 246.0,
  "end_seconds": 318.0,
  "duration_seconds": 72.0,
  "excerpt": "Transcript excerpt...",
  "reasoning": "Why this clip matters...",
  "rank": 1,
  "score": {
    "total_score": 82,
    "icp_relevance": 84,
    "tkxel_alignment": 78,
    "hook_strength": 86,
    "virality_potential": 80,
    "business_value": 83,
    "guest_authority": 90,
    "topic_fit": 84,
    "audio_confidence": 72,
    "explanation": "Score explanation..."
  },
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
      "render_type": "vertical",
      "status": "completed",
      "filename": "01-short-vertical-246.mp4",
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
  "release": "aurora-prism-mvp"
}
```

## Episodes

### GET `/episodes`

Lists all episodes, newest first.

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
    "theme": "Episode theme",
    "status": "analyzed",
    "clip_count": 10,
    "asset_count": 4,
    "transcript_segment_count": 603
  }
]
```

### POST `/episodes`

Creates a new episode. Status defaults to `draft`.

Input JSON:

```json
{
  "title": "Dr. Seth Dobrin - Preventing Global Tech Homogenization",
  "guest_name": "Dr. Seth Dobrin",
  "guest_role": "Founder and CEO",
  "guest_company": "Qantm AI",
  "recording_date": "2024-11-25",
  "theme": "Preventing Global Tech Homogenization"
}
```

Required fields:

- `title`

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
  "tkxel_services": "AI strategy, product engineering, data platforms",
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

Uploads or pastes a timestamped transcript. Existing transcript segments for the episode are replaced.

Content type:

```text
multipart/form-data
```

Option A input fields:

- `file`: transcript file
- `source_format`: optional, one of `txt`, `vtt`, `srt`, `csv`

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

Example with file:

```bash
curl -X POST http://localhost:8100/api/episodes/{episode_id}/transcript \
  -F "source_format=txt" \
  -F "file=@seth-dobrin-bt-podcast.txt"
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
- `404` if the episode does not exist

## Analysis

### POST `/episodes/{episode_id}/analyze`

Runs clip recommendation analysis for an episode. A transcript must already exist.

Path params:

- `episode_id`: episode UUID

Input JSON:

```json
{
  "ai_provider": "azure_openai",
  "clip_types": ["short", "highlight"],
  "duration_min_seconds": null,
  "duration_max_seconds": null,
  "target_clip_count": 10,
  "platforms": ["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
  "custom_instructions": "Focus on AI governance and avoid salesy clips.",
  "mode": "mock"
}
```

Field notes:

- `ai_provider`: `azure_openai` or `openai`
- `clip_types`: use `short`, `highlight`, or both
- `duration_min_seconds` and `duration_max_seconds`: optional custom override
- `target_clip_count`: 1 to 30
- `mode`: currently stored on the analysis run; default is `mock`

Default durations:

- `short`: 30-90 seconds
- `highlight`: 180-360 seconds

Output:

```json
{
  "id": "analysis-run-uuid",
  "episode_id": "episode-uuid",
  "status": "completed",
  "mode": "mock",
  "summary": "Generated 10 recommended clips across short, highlight using azure_openai provider settings.",
  "generated_clip_count": 10
}
```

Errors:

- `400` if transcript is missing or the episode does not exist

## Clips

### GET `/episodes/{episode_id}/clips`

Lists clip recommendations for an episode.

Path params:

- `episode_id`: episode UUID

Query params:

- `clip_type`: optional, `short` or `highlight`
- `status`: optional clip status

Output:

```json
[
  {
    "id": "clip-uuid",
    "episode_id": "episode-uuid",
    "clip_type": "short",
    "moment_type": "hot_take",
    "status": "recommended",
    "start_seconds": 246.0,
    "end_seconds": 318.0,
    "duration_seconds": 72.0,
    "excerpt": "Transcript excerpt...",
    "reasoning": "Why this clip matters...",
    "rank": 1,
    "score": {},
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

Fetches one clip recommendation with score, metadata, and rendered outputs.

Path params:

- `clip_id`: clip UUID

Output: `ClipRead`

Errors:

- `404` if the clip does not exist

### PATCH `/clips/{clip_id}/status`

Approves, rejects, or marks a clip for revision. Also creates an approval event.

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
  "render_types": ["original", "vertical"]
}
```

Behavior:

- If source video exists, `original` and `vertical` create MP4 files.
- If only audio exists, `original` falls back to `audio` and `vertical` falls back to `waveform`.
- `audio` creates an audio-only file.
- `waveform` creates a simple 9:16 waveform MP4.

Output:

```json
[
  {
    "id": "render-uuid",
    "render_type": "vertical",
    "status": "completed",
    "filename": "01-short-vertical-246.mp4",
    "error": null
  }
]
```

Errors:

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

Creates a ZIP handoff package for approved clips. If no clips are approved, the current implementation falls back to the top five clips.

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
        "end": "05:18.000",
        "score": 82
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
  -d '{"icp":"B2B tech leaders","hot_topic":"AI strategy","tkxel_services":"AI strategy, product engineering"}'
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
  -d '{"ai_provider":"azure_openai","clip_types":["short","highlight"],"target_clip_count":10,"platforms":["youtube_shorts","tiktok","instagram_reels","linkedin"],"mode":"mock"}'
```

6. Approve a clip:

```bash
curl -X PATCH http://localhost:8100/api/clips/{clip_id}/status \
  -H "Content-Type: application/json" \
  -d '{"status":"approved","user_name":"Demo Reviewer","comments":"Approved for export."}'
```

7. Render clip:

```bash
curl -X POST http://localhost:8100/api/clips/{clip_id}/render \
  -H "Content-Type: application/json" \
  -d '{"render_types":["original","vertical"]}'
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

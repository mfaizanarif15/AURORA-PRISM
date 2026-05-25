from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import Asset, Episode, EpisodeContext, TranscriptSegment
from app.schemas.api import AnalysisRequest
from app.services.analysis import analyze_episode
from app.services.assets import extract_text
from app.services.transcripts import parse_transcript


DEMO_TITLE = "Dr. Seth Dobrin - Preventing Global Tech Homogenization"


async def main() -> None:
    assets_dir = Path(os.getenv("DEMO_ASSETS_DIR", "../Podcast Automation Assets")).resolve()
    transcript_path = assets_dir / "seth-dobrin-bt-podcast.txt"
    video_path = assets_dir / "riverside_seth_& jocelyn _ nov 25, 2024 001_dr._seth dobrin - p.mp4"
    audio_path = assets_dir / "riverside_copy_of seth & jocelyn _ nov 25, 2024 001_dr._seth dobrin - p.wav"
    content_pdf = assets_dir / "Dr Seth Content.pdf"
    questionnaire_pdf = assets_dir / "Dr. Seth_s Questionnaire .pdf"

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(Episode).where(Episode.title == DEMO_TITLE))
        episode = existing.scalar_one_or_none()
        if episode is None:
            episode = Episode(
                title=DEMO_TITLE,
                guest_name="Dr. Seth Dobrin",
                guest_role="Founder and CEO",
                guest_company="Qantm AI",
                recording_date="2024-11-25",
                theme="Preventing Global Tech Homogenization",
                status="draft",
            )
            session.add(episode)
            await session.flush()
            session.add(
                EpisodeContext(
                    episode_id=episode.id,
                    icp="B2B technology leaders, founders, and enterprise teams exploring responsible AI.",
                    target_audience="Executives and senior product/data leaders.",
                    audience_pain_points="AI risk, governance, cultural bias, global representation, cost, and ROI.",
                    tkxel_services="AI strategy, data platforms, product engineering, cloud modernization.",
                    hot_topic="Technological colonialism and AI homogenization",
                    business_objectives="Grow BetterTech's audience and create credible AI strategy conversations.",
                    episode_plan="Find strong shorts and deeper highlights from Dr. Seth's AI governance discussion.",
                    preferred_platforms=["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
                    editor_notes="Keep the framing direct but brand-safe. Avoid overclaiming.",
                )
            )
            for path, asset_type, content_type, is_primary in [
                (video_path, "video", "video/mp4", True),
                (audio_path, "audio", "audio/wav", True),
                (content_pdf, "guest_document", "application/pdf", False),
                (questionnaire_pdf, "guest_document", "application/pdf", False),
            ]:
                if path.exists():
                    session.add(
                        Asset(
                            episode_id=episode.id,
                            asset_type=asset_type,
                            filename=path.name,
                            content_type=content_type,
                            path=str(path),
                            extracted_text=extract_text(path, content_type),
                            tags=["demo"],
                            is_primary=is_primary,
                        )
                    )
            if transcript_path.exists():
                parsed = parse_transcript(transcript_path.read_text(encoding="utf-8", errors="ignore"), "txt")
                for segment in parsed:
                    session.add(
                        TranscriptSegment(
                            episode_id=episode.id,
                            speaker=segment.speaker,
                            start_seconds=segment.start_seconds,
                            end_seconds=segment.end_seconds,
                            text=segment.text,
                            confidence=segment.confidence,
                        )
                    )
            await session.commit()

        await analyze_episode(
            session,
            episode.id,
            AnalysisRequest(
                clip_types=["short", "highlight"],
                target_clip_count=10,
                platforms=["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
                custom_instructions="Prioritize AI governance, cultural bias, business impact, and sharp executive hooks.",
            ),
        )
        print(f"Seeded demo episode: {episode.id}")


if __name__ == "__main__":
    asyncio.run(main())

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.api import AnalysisRequest
from app.services.analysis import (
    DraftClip,
    PlatformMetadataDraft,
    _context_terms,
    _duration_range,
    _langfuse_llm_input,
    _langfuse_llm_output,
    _load_json_response,
    _supporting_document_payloads,
)
from app.services.analysis_graph import SECTION_SPECS, plan_section_jobs


def test_default_duration_ranges() -> None:
    request = AnalysisRequest()
    assert _duration_range("short", request) == (30, 90)
    assert _duration_range("highlight", request) == (180, 360)


def test_custom_duration_overrides_defaults() -> None:
    request = AnalysisRequest(duration_min_seconds=45, duration_max_seconds=120)
    assert _duration_range("short", request) == (45, 120)
    assert _duration_range("highlight", request) == (45, 120)


def test_load_json_response_recovers_complete_clip_objects() -> None:
    malformed = """
{
  "clips": [
    {"source_candidate_id": "candidate_1", "clip_type": "short"}
    {"source_candidate_id": "candidate_2", "clip_type": "highlight"}
  ],
  "summary": "Recovered response"
}
"""

    parsed = _load_json_response(malformed)

    assert parsed["summary"] == "Recovered response"
    assert [clip["source_candidate_id"] for clip in parsed["clips"]] == [
        "candidate_1",
        "candidate_2",
    ]


def test_langfuse_llm_input_includes_raw_messages_when_capture_enabled() -> None:
    settings = SimpleNamespace(langfuse_capture_llm_io=True, langfuse_max_llm_io_chars=250000)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    payload = {"episode": {"id": "episode-1"}, "candidate_moments": [{"id": "candidate_1"}]}

    trace_input = _langfuse_llm_input(settings, messages, payload)

    assert trace_input["messages"] == messages
    assert trace_input["prompt_payload"] == payload


def test_langfuse_llm_input_hashes_messages_when_capture_disabled() -> None:
    settings = SimpleNamespace(langfuse_capture_llm_io=False, langfuse_max_llm_io_chars=250000)
    messages = [{"role": "user", "content": "sensitive transcript prompt"}]

    trace_input = _langfuse_llm_input(settings, messages, {"candidate_moments": []})

    assert trace_input["capture_disabled"] is True
    assert trace_input["messages"][0]["content_length"] == len("sensitive transcript prompt")
    assert "content_sha256" in trace_input["messages"][0]
    assert "content" not in trace_input["messages"][0]


def test_langfuse_llm_output_includes_raw_and_normalized_response() -> None:
    settings = SimpleNamespace(langfuse_capture_llm_io=True, langfuse_max_llm_io_chars=250000)
    draft = DraftClip(
        clip_type="short",
        moment_type="expert_insight",
        start_seconds=10,
        end_seconds=70,
        excerpt="A useful clip excerpt.",
        reasoning="Strong standalone business insight.",
        score_parts={
            "icp_relevance": 80,
            "tkxel_alignment": 80,
            "hook_strength": 80,
            "virality_potential": 80,
            "business_value": 80,
            "guest_authority": 80,
            "topic_fit": 80,
            "audio_confidence": 80,
        },
        metadata_by_platform={
            "linkedin": PlatformMetadataDraft(
                title="Enterprise AI Lesson",
                hook="The practical lesson",
                caption="A grounded caption.",
                soft_cta="Follow for more.",
                business_cta="Talk to TKXEL.",
                hashtags=["#AI"],
            )
        },
    )

    output = _langfuse_llm_output(
        settings,
        '{"clips": [], "summary": "ok"}',
        {"clips": [], "summary": "ok"},
        [draft],
        "stop",
    )

    assert output["assistant_message"]["content"] == '{"clips": [], "summary": "ok"}'
    assert output["parsed_json"]["summary"] == "ok"
    assert output["normalized_clips"][0]["excerpt"] == "A useful clip excerpt."
    assert output["normalized_clips"][0]["platform_metadata"]["linkedin"]["title"] == "Enterprise AI Lesson"


def test_supporting_document_payloads_include_trimmed_extracted_text() -> None:
    document = SimpleNamespace(
        filename="guest-brief.pdf",
        asset_type="guest_document",
        content_type="application/pdf",
        extracted_text="AI governance strategy " * 200,
    )

    payloads = _supporting_document_payloads([document])

    assert len(payloads) == 1
    assert payloads[0]["filename"] == "guest-brief.pdf"
    assert payloads[0]["asset_type"] == "guest_document"
    assert payloads[0]["content_type"] == "application/pdf"
    assert payloads[0]["text_excerpt"].startswith("AI governance strategy")
    assert len(payloads[0]["text_excerpt"]) < len(document.extracted_text)


def test_context_terms_include_supporting_document_text() -> None:
    episode = SimpleNamespace(
        title="Enterprise AI",
        guest_role=None,
        guest_company=None,
    )
    document = SimpleNamespace(extracted_text="Revenue architecture modernization plan")

    terms = _context_terms(episode, None, AnalysisRequest(), [document])

    assert "revenue" in terms
    assert "architecture" in terms
    assert "modernization" in terms


def test_analysis_request_defaults_to_three_per_enabled_section() -> None:
    request = AnalysisRequest()

    jobs = plan_section_jobs(request)

    assert [job.spec.key for job in jobs] == ["tiktok", "instagram_reels", "youtube_shorts", "linkedin"]
    assert {job.target_count for job in jobs} == {3}


def test_section_jobs_use_per_section_custom_durations() -> None:
    request = AnalysisRequest(
        sections={
            "tiktok": {
                "enabled": True,
                "target_count": 2,
                "duration_min_seconds": 20,
                "duration_max_seconds": 50,
            },
            "instagram_reels": {"enabled": False, "target_count": 3},
            "youtube_shorts": {"enabled": False, "target_count": 3},
            "linkedin": {"enabled": False, "target_count": 3},
            "highlights": {
                "enabled": True,
                "target_count": 1,
                "duration_min_seconds": 240,
                "duration_max_seconds": 420,
            },
        }
    )

    jobs = plan_section_jobs(request)

    assert [(job.spec.key, job.spec.min_seconds, job.spec.max_seconds, job.target_count) for job in jobs] == [
        ("tiktok", 20, 50, 2),
        ("highlights", 240, 420, 1),
    ]


def test_section_jobs_keep_legacy_global_duration_override() -> None:
    request = AnalysisRequest(duration_min_seconds=40, duration_max_seconds=80)

    jobs = plan_section_jobs(request)

    assert jobs
    assert {(job.spec.min_seconds, job.spec.max_seconds) for job in jobs} == {(40, 80)}


def test_section_duration_rejects_min_greater_than_max() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(
            sections={
                "tiktok": {
                    "enabled": True,
                    "target_count": 3,
                    "duration_min_seconds": 90,
                    "duration_max_seconds": 30,
                }
            }
        )


def test_section_prompt_specs_are_specialized() -> None:
    assert SECTION_SPECS["tiktok"].max_seconds == 60
    assert SECTION_SPECS["instagram_reels"].target_platform == "instagram_reels"
    assert SECTION_SPECS["youtube_shorts"].focus
    assert SECTION_SPECS["linkedin"].min_seconds == 45
    assert SECTION_SPECS["highlights"].clip_type == "highlight"

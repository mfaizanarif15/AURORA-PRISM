from types import SimpleNamespace

from app.schemas.api import AnalysisRequest
from app.services.analysis import (
    DraftClip,
    PlatformMetadataDraft,
    _duration_range,
    _langfuse_llm_input,
    _langfuse_llm_output,
    _load_json_response,
)


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

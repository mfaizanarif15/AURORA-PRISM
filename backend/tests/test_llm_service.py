from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import llm


@pytest.mark.asyncio
async def test_call_chat_completion_wraps_langfuse_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        ai_provider="azure_openai",
        langfuse_capture_llm_io=True,
        langfuse_max_llm_io_chars=250000,
    )
    create_kwargs: dict[str, Any] = {}

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            create_kwargs.update(kwargs)
            return SimpleNamespace(
                id="completion-1",
                created=123,
                model="deployment-1",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"title": "Practical AI Strategy"}'),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7, total_tokens=19),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    observations: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    @contextmanager
    def fake_observation(*args: Any, **kwargs: Any):
        observations.append({"args": args, **kwargs})
        yield SimpleNamespace(update=lambda **values: updates.append(values))

    monkeypatch.setattr(llm, "make_chat_client", lambda *_args, **_kwargs: fake_client)
    monkeypatch.setattr(llm, "chat_model_name", lambda *_args, **_kwargs: "deployment-1")
    monkeypatch.setattr(llm, "observation", fake_observation)

    result = await llm.call_chat_completion(
        operation="episode_title_generation",
        name="llm_episode_title_generation",
        provider="azure_openai",
        settings=settings,
        messages=[{"role": "user", "content": "Suggest a title"}],
        payload={"episode": {"id": "episode-1"}},
        temperature=0.2,
        max_tokens=120,
        response_format={"type": "json_object"},
        prompt_version="episode-title-json-v1",
    )

    assert result.content == '{"title": "Practical AI Strategy"}'
    assert create_kwargs["model"] == "deployment-1"
    assert create_kwargs["response_format"] == {"type": "json_object"}
    assert observations[0]["args"] == ("llm_episode_title_generation",)
    assert observations[0]["as_type"] == "generation"
    assert observations[0]["metadata"]["operation"] == "episode_title_generation"
    assert observations[0]["input"]["prompt_payload"]["episode"]["id"] == "episode-1"
    assert updates[0]["usage_details"] == {"input": 12, "output": 7, "total": 19}


@pytest.mark.asyncio
async def test_suggest_episode_title_uses_standard_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = SimpleNamespace(
        id="episode-1",
        title="Untitled episode",
        guest_name="Dr. Ada",
        guest_role="CTO",
        guest_company="ExampleCo",
    )
    context = SimpleNamespace(
        target_audience="B2B technology leaders",
        hot_topic="AI strategy",
        business_objectives="Generate practical demand",
        episode_plan=None,
        editor_notes=None,
    )
    segment = SimpleNamespace(text="AI strategy needs clear product outcomes.")
    calls: list[dict[str, Any]] = []

    async def fake_call_chat_completion(**kwargs: Any) -> llm.LLMCallResult:
        calls.append(kwargs)
        return llm.LLMCallResult(
            content='{"title": "AI Strategy With Dr. Ada"}',
            raw_response=None,
            finish_reason="stop",
            usage_details=None,
            model="deployment-1",
            provider="azure_openai",
        )

    monkeypatch.setattr(llm, "call_chat_completion", fake_call_chat_completion)

    title = await llm.suggest_episode_title(episode, context, [segment], "azure_openai")

    assert title == "AI Strategy With Dr. Ada"
    assert calls[0]["operation"] == "episode_title_generation"
    assert calls[0]["name"] == "llm_episode_title_generation"
    assert calls[0]["prompt_version"] == llm.TITLE_PROMPT_VERSION
    assert calls[0]["payload"]["transcript_excerpt"] == segment.text

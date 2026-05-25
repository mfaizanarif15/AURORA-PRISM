from app.schemas.api import AnalysisRequest
from app.services.analysis import _duration_range


def test_default_duration_ranges() -> None:
    request = AnalysisRequest()
    assert _duration_range("short", request) == (30, 90)
    assert _duration_range("highlight", request) == (180, 360)


def test_custom_duration_overrides_defaults() -> None:
    request = AnalysisRequest(duration_min_seconds=45, duration_max_seconds=120)
    assert _duration_range("short", request) == (45, 120)
    assert _duration_range("highlight", request) == (45, 120)

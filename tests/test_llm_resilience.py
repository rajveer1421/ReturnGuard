"""The LLM wrapper must never hang a request and must surface failures as LLMError."""
import time

import pytest
from pydantic import BaseModel

from returnguard import config, llm


class Out(BaseModel):
    answer: str


class FakeRunnable:
    def __init__(self, errors, result=None):
        self.errors, self.result, self.calls = list(errors), result, 0

    def invoke(self, _messages):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"parsed": self.result, "raw": None}


class FakeChat:
    def __init__(self, runnable):
        self.runnable = runnable

    def with_structured_output(self, *_a, **_k):
        return self.runnable


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(config, "LLM_CACHE", False)
    monkeypatch.setattr(config, "LLM_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def install(runnable):
        monkeypatch.setattr(llm, "_chat", lambda model: FakeChat(runnable))
        return runnable
    return install


def test_transient_error_is_retried(fake):
    r = fake(FakeRunnable([ConnectionError("reset")], Out(answer="ok")))
    parsed, rec = llm.call_structured("t", Out, "sys", [llm.text_part("hi")])
    assert parsed.answer == "ok" and rec.attempts == 2 and r.calls == 2


def test_invalid_output_is_retried_then_fails(fake):
    fake(FakeRunnable([], None))  # model never returns schema-valid JSON
    with pytest.raises(llm.LLMError) as exc:
        llm.call_structured("t", Out, "sys", [llm.text_part("hi")])
    assert exc.value.record.ok is False and exc.value.record.attempts == config.LLM_MAX_RETRIES + 1


def test_permission_denied_is_not_retried(fake):
    denied = RuntimeError("403 PERMISSION_DENIED. Your project has been denied access.")
    r = fake(FakeRunnable([denied, denied, denied, denied]))
    with pytest.raises(llm.LLMError):
        llm.call_structured("t", Out, "sys", [llm.text_part("hi")])
    assert r.calls == 1


def test_exhausted_daily_quota_fails_fast_instead_of_sleeping(fake):
    quota = RuntimeError("429 RESOURCE_EXHAUSTED ... 'retryDelay': '79162s'")
    r = fake(FakeRunnable([quota, quota, quota, quota]))
    start = time.monotonic()
    with pytest.raises(llm.LLMError):
        llm.call_structured("t", Out, "sys", [llm.text_part("hi")])
    assert r.calls == 1 and time.monotonic() - start < 5


def test_missing_api_key_is_an_llm_error_not_a_crash(monkeypatch):
    def no_key(_model):
        raise ValueError("API key required for Gemini Developer API")
    monkeypatch.setattr(llm, "_chat", no_key)
    with pytest.raises(llm.LLMError) as exc:
        llm.call_structured("identity_fingerprint", Out, "system", [])
    assert exc.value.record.ok is False and "API key" in exc.value.record.error

"""Regression tests for the generic AI provider abstraction (PRD R3.1 / P1.2).

Verifies the provider registry drives dispatch, that one OpenAI-compatible
path serves Groq/Ollama/OpenAI-style endpoints, and that old provider
configurations (segmented Groq key, keyless Ollama) keep working.
"""
import pandas as pd
import pytest
import requests

from core.ai_client import AIWorker, PROVIDERS, get_provider

pytest.importorskip("PyQt6")


def _frames():
    return pd.DataFrame()


def test_providers_registered():
    assert set(PROVIDERS) >= {"Anthropic", "Groq", "Ollama", "OpenAI"}
    assert get_provider("Anthropic").kind == "anthropic"
    assert get_provider("Groq").kind == "openai_compatible"
    assert get_provider("Groq").base_url == "https://api.groq.com/openai/v1"
    assert get_provider("Ollama").base_url == "http://localhost:11434/v1"
    assert get_provider("Ollama").needs_key is False
    assert get_provider("OpenAI").base_url == "https://api.openai.com/v1"


def test_unknown_provider_falls_back_to_anthropic():
    assert get_provider("NoSuchProvider").name == "Anthropic"


def test_model_default_resolved_from_registry():
    assert AIWorker(api_key="k", id_hex="0", frames_df=_frames(),
                    provider="OpenAI").model == "gpt-4o-mini"
    assert AIWorker(api_key="k", id_hex="0", frames_df=_frames(),
                    provider="Ollama").model == "llama3.1"
    # An explicit model always wins over the registry default.
    assert AIWorker(api_key="k", id_hex="0", frames_df=_frames(),
                    provider="OpenAI", model="qwen-plus").model == "qwen-plus"


def test_groq_resolves_separate_key():
    w = AIWorker(api_key="main", groq_key="gk", id_hex="0", frames_df=_frames(),
                 provider="Groq")
    assert w._resolve_key() == "gk"
    # Falls back to api_key when groq_key absent (old configs).
    w2 = AIWorker(api_key="main", id_hex="0", frames_df=_frames(),
                  provider="Groq")
    assert w2._resolve_key() == "main"


class _FakeResp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


_STREAM_LINES = [
    b'data: {"choices":[{"delta":{"content":"Hello "}}]}',
    b'data: {"choices":[{"delta":{"content":"world"}}]}',
    b'data: [DONE]',
]


def _capture(monkeypatch):
    calls = {}
    def fake(url, **kw):
        calls.update({"url": url, **kw})
        return _FakeResp(_STREAM_LINES)
    monkeypatch.setattr(requests, "post", fake)
    return calls


def test_openai_compatible_streams_and_accumulates(monkeypatch):
    calls = _capture(monkeypatch)
    w = AIWorker(api_key="k", id_hex="0", frames_df=_frames(), provider="OpenAI")
    w._run_openai_compatible("https://api.openai.com/v1", "k",
                             "gpt-4o-mini", "OpenAI")
    assert calls["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer k"
    assert calls["json"]["model"] == "gpt-4o-mini"
    assert w._full_response == "Hello world"


def test_run_dispatches_to_openai_compatible(monkeypatch):
    _capture(monkeypatch)
    w = AIWorker(api_key="k", id_hex="0", frames_df=_frames(), provider="OpenAI")
    w.run()
    assert w._full_response == "Hello world"


def test_ollama_is_keyless(monkeypatch):
    calls = _capture(monkeypatch)
    w = AIWorker(api_key="", id_hex="0", frames_df=_frames(), provider="Ollama")
    w._run_openai_compatible("http://localhost:11434/v1", "",
                             "llama3.1", "Ollama")
    assert "Authorization" not in calls["headers"]
    assert calls["url"] == "http://localhost:11434/v1/chat/completions"


def test_openai_compatible_auth_error_message(monkeypatch):
    class _E(requests.HTTPError):
        def __init__(self):
            super().__init__()
            self.response = type("R", (), {"status_code": 401})()

    def _boom(url, **_):
        raise _E()

    monkeypatch.setattr(requests, "post", _boom)
    errs = []
    w = AIWorker(api_key="k", id_hex="0", frames_df=_frames(), provider="Groq")
    w.error.connect(errs.append)
    w._run_openai_compatible("https://api.groq.com/openai/v1", "k",
                             "llama-3.3-70b-versatile", "Groq")
    assert errs == ["Invalid Groq API key. Check Settings > API Keys."]


def test_openai_compatible_connection_error_message(monkeypatch):
    def _boom(url, **_):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", _boom)
    errs = []
    w = AIWorker(api_key="k", id_hex="0", frames_df=_frames(), provider="Ollama")
    w.error.connect(errs.append)
    w._run_openai_compatible("http://localhost:11434/v1", "",
                             "llama3.1", "Ollama")
    assert errs and "Cannot reach Ollama" in errs[0]
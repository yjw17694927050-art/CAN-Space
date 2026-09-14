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


# ── Domestic providers (PRD R3.2 / P2.2) ──────────────────────────────────────

def test_domestic_providers_registered():
    domestic = {"Qwen", "DeepSeek", "Kimi", "GLM"}
    assert domestic <= set(PROVIDERS)
    for name in domestic:
        spec = get_provider(name)
        assert spec.kind == "openai_compatible", name
        assert spec.base_url.startswith("https://"), name
        assert spec.needs_key is True, name
        assert spec.models and spec.default_model in spec.models, name


def test_domestic_provider_dispatches_with_registry_base_url(monkeypatch):
    calls = _capture(monkeypatch)
    w = AIWorker(api_key="sk-test", id_hex="0", frames_df=_frames(),
                 provider="DeepSeek")
    w.run()
    assert calls["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert calls["json"]["model"] == "deepseek-chat"
    assert w._full_response == "Hello world"


def test_base_url_override_wins_over_registry(monkeypatch):
    """Custom/compatible endpoints (e.g. Volcengine Ark) work via base_url."""
    calls = _capture(monkeypatch)
    w = AIWorker(api_key="sk-test", id_hex="0", frames_df=_frames(),
                 provider="Qwen", model="qwen-plus",
                 base_url="https://ark.cn-beijing.volces.com/api/v3")
    w.run()
    assert calls["url"] == \
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def test_ai_models_derived_from_registry():
    import settings_dialog
    assert settings_dialog.AI_MODELS["Qwen"] == list(get_provider("Qwen").models)
    assert "OpenAI" in settings_dialog.AI_MODELS  # was missing before P2.2


def test_per_provider_model_and_base_url_persistence():
    from PyQt6.QtCore import QSettings
    from settings_dialog import (
        load_provider_model, save_provider_model,
        load_provider_base_url, save_provider_base_url,
    )
    qs = QSettings("CAN-Space", "CAN-Space")
    try:
        save_provider_model("DeepSeek", "deepseek-reasoner")
        assert load_provider_model("DeepSeek") == "deepseek-reasoner"
        save_provider_base_url("DeepSeek", "https://proxy.example.com/v1")
        assert load_provider_base_url("DeepSeek") == \
            "https://proxy.example.com/v1"
        # Unset provider falls back to registry defaults
        assert load_provider_model("Qwen") == "qwen-plus"
        assert load_provider_base_url("Qwen") == \
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
    finally:
        qs.remove("ai_model_deepseek")
        qs.remove("ai_base_url_deepseek")


def test_per_provider_key_roundtrip_with_mocked_keyring(monkeypatch):
    import settings_dialog
    store = {}
    monkeypatch.setattr(settings_dialog.keyring, "set_password",
                        lambda svc, slot, val: store.__setitem__(slot, val))
    monkeypatch.setattr(settings_dialog.keyring, "get_password",
                        lambda svc, slot: store.get(slot))
    settings_dialog.save_provider_key("Kimi", "sk-kimi")
    assert settings_dialog.load_provider_key("Kimi") == "sk-kimi"
    # Legacy fallbacks keep old configs working
    settings_dialog.save_api_key("sk-ant-legacy")
    assert settings_dialog.load_provider_key("Anthropic") == "sk-ant-legacy"
    settings_dialog.save_groq_key("gsk-legacy")
    assert settings_dialog.load_provider_key("Groq") == "gsk-legacy"
    assert settings_dialog.load_provider_key("GLM") == ""
    # Empty keys must not clobber a stored one
    settings_dialog.save_provider_key("Kimi", "")
    assert settings_dialog.load_provider_key("Kimi") == "sk-kimi"


def test_settings_dialog_per_provider_ui(qtbot, monkeypatch):
    """Settings dialog lists all registry providers incl. domestic ones, and
    switching provider refreshes key/base_url/model fields (P2.2)."""
    import settings_dialog
    store = {}
    monkeypatch.setattr(settings_dialog.keyring, "set_password",
                        lambda svc, slot, val: store.__setitem__(slot, val))
    monkeypatch.setattr(settings_dialog.keyring, "get_password",
                        lambda svc, slot: store.get(slot))
    dlg = settings_dialog.SettingsDialog()
    qtbot.add_widget(dlg)

    listed = {dlg.provider_combo.itemText(i)
              for i in range(dlg.provider_combo.count())}
    assert {"Anthropic", "Groq", "Ollama", "OpenAI",
            "Qwen", "DeepSeek", "Kimi", "GLM"} <= listed

    dlg.provider_combo.setCurrentText("DeepSeek")
    assert dlg.base_url_edit.text() == "https://api.deepseek.com/v1"
    assert dlg.model_combo.currentText() == "deepseek-chat"
    assert dlg.provider_key_edit.isEnabled()

    # Edits survive a provider round-trip (stash-on-switch)
    dlg.provider_key_edit.setText("sk-ds")
    dlg.base_url_edit.setText("https://custom.deepseek.cn/v1")
    dlg.provider_combo.setCurrentText("Ollama")
    assert not dlg.provider_key_edit.isEnabled()   # keyless local server
    assert dlg.base_url_edit.text() == "http://localhost:11434/v1"
    dlg.provider_combo.setCurrentText("DeepSeek")
    assert dlg.provider_key_edit.text() == "sk-ds"
    assert dlg.base_url_edit.text() == "https://custom.deepseek.cn/v1"

    # Anthropic (native SDK) hides base-url editing
    dlg.provider_combo.setCurrentText("Anthropic")
    assert not dlg.base_url_edit.isEnabled()
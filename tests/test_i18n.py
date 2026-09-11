"""Regression tests for the i18n foundation (PRD R1.1/R1.2, P1.3).

Covers the lightweight language packs, switch/fallback semantics, and the
wiring that makes the AI engine's output language follow the UI language
(PRD R1.3).
"""
import pandas as pd
import pytest

from core import i18n
from core.i18n import tr


def _reset_to_zh():
    i18n.set_language(i18n.LANGUAGE_ZH)


def test_default_language_is_chinese():
    _reset_to_zh()
    assert i18n.current_language() == i18n.LANGUAGE_ZH


def test_tr_returns_chinese_for_known_key():
    _reset_to_zh()
    assert tr("app.title") == "CAN-Space — CAN 逆向工程工作台"
    assert tr("tab.frames") == "帧"


@pytest.mark.parametrize("code", ["en", "zh", "xx-invalid"])
def test_language_switch(code):
    i18n.set_language(code)
    if code == "en":
        assert i18n.current_language() == "en"
        assert tr("tab.dbc") == "DBC BUILDER"
    elif code == "zh":
        assert i18n.current_language() == "zh"
        assert tr("tab.dbc") == "DBC 生成器"
    else:  # invalid → ignored, keeps previous
        assert i18n.current_language() == "zh"
    _reset_to_zh()


def test_missing_key_falls_back_to_english_then_key():
    _reset_to_zh()
    # Key exists in English but not (fully) in Chinese → English fallback.
    _ZH_has = False
    # We add a never-translated key on the fly:
    i18n._LANG[i18n.LANGUAGE_EN]["__probe_only"] = "EnglishText"
    assert tr("__probe_only") == "EnglishText"
    i18n._LANG[i18n.LANGUAGE_EN].pop("__probe_only")
    # Fully unknown key → the key itself (never blank).
    assert tr("no/such/key") == "no/such/key"


def test_tr_placeholder_formatting():
    i18n._LANG[i18n.LANGUAGE_ZH]["__who"] = "你好，{name}"
    try:
        assert tr("__who", name="CAN") == "你好，CAN"
    finally:
        del i18n._LANG[i18n.LANGUAGE_ZH]["__who"]
    _reset_to_zh()


def test_t_alias_equals_tr():
    assert i18n.t is tr


def test_ai_system_prompt_follows_ui_language():
    pytest.importorskip("PyQt6")
    from core.ai_client import AIWorker

    i18n.set_language(i18n.LANGUAGE_ZH)
    w_zh = AIWorker(api_key="", id_hex="0", frames_df=pd.DataFrame())
    assert "信号识别" in w_zh._system_prompt

    i18n.set_language(i18n.LANGUAGE_EN)
    w_en = AIWorker(api_key="", id_hex="0", frames_df=pd.DataFrame())
    assert "SIGNAL IDENTIFICATION" in w_en._system_prompt

    _reset_to_zh()


def test_build_system_prompt_zh_ground_truth():
    from core.vehicle_pack import build_system_prompt
    prompt = build_system_prompt("generic", language="zh")
    assert "信号识别" in prompt
    assert "建议的 DBC 条目" in prompt
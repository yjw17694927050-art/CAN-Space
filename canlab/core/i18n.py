"""Lightweight dictionary-based i18n for CAN-Space (PRD R1.1/R1.2).

Chosen over Qt ``tr()`` + ``.ts`` for a small single-author project: a plain
Python dict keeps translations readable in-repo and avoids lrelease tooling.

Guarantees:
- Unknown keys fall back to English (then to the key itself), so a missing
  translation never breaks or blanks the UI.
- This module is GUI-free and headless-testable (``core/`` rule).
"""
from __future__ import annotations

LANGUAGE_ZH = "zh"
LANGUAGE_EN = "en"

SUPPORTED_LANGUAGES = (LANGUAGE_ZH, LANGUAGE_EN)

_current = LANGUAGE_ZH

# Key → translated text, per language. English is the complete fallback source.
_ZH = {
    # window / tabs
    "app.title": "CAN-Space — CAN 逆向工程工作台",
    "tab.frames": "帧",
    "tab.signals": "信号",
    "tab.plot": "绘图",
    "tab.ai": "AI 引擎 ★",
    "tab.dbc": "DBC 生成器",
    "tab.codegen": "代码生成",
    "tab.intelligence": "智能分析",
    "tab.injection": "注入",
    "tab.diagnostics": "诊断",
    "tab.dashboard": "仪表盘",
    "tab.autore": "自动逆向 ★",
    "tab.timeline": "时间轴 ★",
    "tab.obd": "OBD-II ★",
    "tab.mlintel": "ML 智能 ★",
    "tab.gateway": "网关 ★",
    # settings dialog
    "settings.language": "语言 / Language",
    "settings.language.zh": "中文",
    "settings.language.en": "English",
    "settings.ai_provider": "AI 提供商",
    "settings.model": "模型",
    "settings.active_ai": "当前 AI 提供商",
    "settings.reset": "重置为默认",
}

_EN = {
    "app.title": "CAN-Space — CAN Reverse Engineering Workbench",
    "tab.frames": "FRAMES",
    "tab.signals": "SIGNALS",
    "tab.plot": "PLOT",
    "tab.ai": "AI ENGINE ★",
    "tab.dbc": "DBC BUILDER",
    "tab.codegen": "CODE GEN",
    "tab.intelligence": "INTELLIGENCE",
    "tab.injection": "INJECTION",
    "tab.diagnostics": "DIAGNOSTICS",
    "tab.dashboard": "DASHBOARD",
    "tab.autore": "AUTO-RE ★",
    "tab.timeline": "TIMELINE ★",
    "tab.obd": "OBD-II ★",
    "tab.mlintel": "ML INTEL ★",
    "tab.gateway": "GATEWAY ★",
    "settings.language": "Language",
    "settings.language.zh": "Chinese",
    "settings.language.en": "English",
    "settings.ai_provider": "Provider",
    "settings.model": "Model",
    "settings.active_ai": "Active AI Provider",
    "settings.reset": "Reset to defaults",
}

_LANG: dict[str, dict[str, str]] = {LANGUAGE_ZH: _ZH, LANGUAGE_EN: _EN}


def current_language() -> str:
    """ISO code of the active language (e.g. 'zh' or 'en')."""
    return _current


def set_language(code: str) -> None:
    """Switch the active language; invalid codes are ignored."""
    global _current
    if code in _LANG:
        _current = code


def tr(key: str, **fmt) -> str:
    """Translate ``key`` in the active language, filling ``fmt`` placeholders.

    Falls back to English, then to the key itself, so a missing entry never
    renders empty text. ``{name}`` placeholders are filled from ``fmt``.
    """
    table = _LANG.get(_current, {})
    template = table.get(key)
    if template is None:
        template = _LANG.get(LANGUAGE_EN, {}).get(key, key)
    if fmt:
        try:
            return template.format(**fmt)
        except (KeyError, IndexError, ValueError):
            pass
    return template


# Convenience alias matching PyQt's short call style.
t = tr
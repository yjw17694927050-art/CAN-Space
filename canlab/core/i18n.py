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
    # common
    "common.close": "关闭",
    # frames tab
    "frames.filter.id": "ID:",
    "frames.filter.id_ph": "ID 过滤（十六进制）...",
    "frames.filter.bus": "总线:",
    "frames.follow": "跟随",
    "frames.freeze": "冻结",
    "frames.frozen": "已冻结",
    "frames.count": "{shown} / {total} 帧",
    "frames.detail.title": "帧详情",
    "frames.detail.title_id": "帧详情 — 0x{id_}",
    "frames.detail.id": "ID:        0x{id}",
    "frames.detail.ts": "时间戳: {value}",
    "frames.detail.header": "字节  十六进制  十进制  二进制",
    # signals tab
    "signals.classify": "自动分类全部",
    "signals.filter": "过滤:",
    "signals.export": "导出 CSV",
    "signals.export_csv_title": "导出 CSV",
    "signals.analyzing": "分析中...",
    "signals.classified_done": "已分类 {n} 个 ID",
    # plot tab
    "plot.signals.label": "信号",
    "plot.clear_all": "全部清除",
    "plot.live_off": "实时: 关",
    "plot.live_on": "实时: 开",
    "plot.screenshot": "截图",
    "plot.save_screenshot": "保存截图",
    "plot.screenshot_fail": "无法保存截图: {err}",
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
    # common
    "common.close": "Close",
    # frames tab
    "frames.filter.id": "ID:",
    "frames.filter.id_ph": "hex filter...",
    "frames.filter.bus": "Bus:",
    "frames.follow": "Follow",
    "frames.freeze": "Freeze",
    "frames.frozen": "Frozen",
    "frames.count": "{shown} / {total} frames",
    "frames.detail.title": "Frame Detail",
    "frames.detail.title_id": "Frame Detail — 0x{id_}",
    "frames.detail.id": "ID:        0x{id}",
    "frames.detail.ts": "Timestamp: {value}",
    "frames.detail.header": "Byte  Hex  Dec  Bin",
    # signals tab
    "signals.classify": "Auto-classify All",
    "signals.filter": "Filter:",
    "signals.export": "Export CSV",
    "signals.export_csv_title": "Export CSV",
    "signals.analyzing": "Analyzing...",
    "signals.classified_done": "Classified {n} IDs",
    # plot tab
    "plot.signals.label": "SIGNALS",
    "plot.clear_all": "Clear All",
    "plot.live_off": "LIVE: OFF",
    "plot.live_on": "LIVE: ON",
    "plot.screenshot": "Screenshot",
    "plot.save_screenshot": "Save Screenshot",
    "plot.screenshot_fail": "Could not save screenshot: {err}",
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
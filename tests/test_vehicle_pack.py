"""Regression tests for vehicle knowledge packs (PRD R1.4 / ROADMAP P1.1).

Verifies that the AI engine's system prompt is assembled from a configurable
vehicle pack instead of a hardcoded Hyundai/Kona prompt, and that a generic
default exists when no pack is selected.
"""
import pytest

from core.vehicle_pack import (
    _pack_dir,
    build_system_prompt,
    get_pack,
    load_all_packs,
)


def test_get_pack_generic_has_no_vehicle():
    pack = get_pack("generic")
    assert pack.name == "generic"
    assert pack.vehicle == ""  # not vehicle-specific


def test_get_pack_hyundai_preserves_kona():
    pack = get_pack("hyundai_kia")
    assert pack.vehicle == "Hyundai Kona"
    assert pack.bus_speed_kbps == 500
    assert pack.byte_order == "little-endian"


def test_get_pack_unknown_falls_back_to_generic():
    pack = get_pack("nonexistent_vehicle")
    assert pack.name == "generic"


def test_default_system_prompt_mentions_no_vehicle():
    prompt = build_system_prompt("generic")
    assert prompt.lower().find("hyundai") == -1
    assert prompt.lower().find("kona") == -1


def test_hyundai_prompt_mentions_kona():
    prompt = build_system_prompt("hyundai_kia")
    assert "Hyundai Kona" in prompt


def test_build_system_prompt_accepts_pack_object():
    from core.vehicle_pack import VehiclePack
    pack = VehiclePack(name="custom", vehicle="Some EV", counter_notes="nibble 0")
    prompt = build_system_prompt(pack)
    assert "Some EV" in prompt
    assert "nibble 0" in prompt


def test_chinese_language_switch():
    prompt = build_system_prompt("generic", language="zh")
    assert "信号识别" in prompt
    assert "置信度" in prompt


@pytest.mark.parametrize("pack_name,key,expected", [
    ("generic", "vehicle", ""),
    ("hyundai_kia", "vehicle", "Hyundai Kona"),
])
def test_json_packs_load(pack_name, key, expected):
    packs = load_all_packs()
    assert pack_name in packs
    assert getattr(packs[pack_name], key) == expected


def test_pack_json_directory_present():
    assert _pack_dir().is_dir()
    files = sorted(p.name for p in _pack_dir().glob("*.json"))
    assert "generic.json" in files
    assert "hyundai_kia.json" in files


def test_aiworker_default_pack_is_generic():
    pytest.importorskip("PyQt6")
    import pandas as pd
    from core.ai_client import AIWorker

    gw = AIWorker(api_key="", id_hex="0", frames_df=pd.DataFrame())
    assert "hyundai" not in gw._system_prompt.lower()
    assert "kona" not in gw._system_prompt.lower()

    hw = AIWorker(api_key="", id_hex="0", frames_df=pd.DataFrame(),
                  vehicle_pack="hyundai_kia")
    assert "Hyundai Kona" in hw._system_prompt


def test_save_load_vehicle_pack_roundtrip():
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QSettings
    from settings_dialog import load_vehicle_pack, save_vehicle_pack

    qs = QSettings("CAN-Space", "CAN-Space")
    original = qs.value("vehicle_pack", None)
    try:
        save_vehicle_pack("hyundai_kia")
        assert load_vehicle_pack() == "hyundai_kia"
    finally:
        if original is None:
            qs.remove("vehicle_pack")
        else:
            qs.setValue("vehicle_pack", original)


def test_load_vehicle_pack_defaults_and_unknown_fall_back():
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QSettings
    from settings_dialog import load_vehicle_pack, save_vehicle_pack

    qs = QSettings("CAN-Space", "CAN-Space")
    original = qs.value("vehicle_pack", None)
    try:
        qs.remove("vehicle_pack")
        assert load_vehicle_pack() == "generic"
        save_vehicle_pack("nonexistent_pack")
        assert load_vehicle_pack() == "generic"
    finally:
        if original is None:
            qs.remove("vehicle_pack")
        else:
            qs.setValue("vehicle_pack", original)


def test_set_ai_config_accepts_vehicle_pack(qtbot):
    pytest.importorskip("PyQt6")
    from tabs.ai_engine_tab import AIEngineTab

    tab = AIEngineTab()
    qtbot.addWidget(tab)
    assert tab._vehicle_pack == "generic"
    tab.set_ai_config(provider="Anthropic", model="claude-sonnet-5",
                      vehicle_pack="hyundai_kia")
    assert tab._vehicle_pack == "hyundai_kia"
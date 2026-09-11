"""Vehicle knowledge packs for the AI engine.

Each pack describes the characteristics of a vehicle (or an open/generic
baseline) that are relevant to CAN reverse-engineering, allowing the AI
system prompt to be assembled per-vehicle WITHOUT editing code
(PRD R1.4 / ROADMAP Phase 1.1).

Packs are pure data. Builtin packs are defined below in Python and also
mirrored as editable JSON files under ``canlab/vehicle_packs/``; users may
drop additional ``*.json`` files there (or point ``load_all_packs`` at a
custom directory) to add/extend packs at runtime.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class VehiclePack:
    """Canonical characteristics for a target vehicle's CAN network."""

    name: str
    label: str = ""
    vehicle: str = ""                      # empty → not vehicle-specific
    bus_speed_kbps: int = 500
    byte_order: str = "little-endian"
    counter_notes: str = ""
    checksum_notes: str = ""
    extra_guidance: str = ""

    def display_name(self) -> str:
        return self.label or self.name


_BUILTIN_PACKS: dict[str, VehiclePack] = {
    "generic": VehiclePack(
        name="generic",
        label="通用 / Generic",
        vehicle="",
        bus_speed_kbps=500,
        byte_order="little-endian",
        counter_notes=(
            "Rolling counters commonly occupy a reserved nibble of a data byte; "
            "confirm by the '-1,0,1,2...' increment pattern and wrap-over before "
            "assuming a counter."
        ),
        checksum_notes=(
            "If a checksum is suspected, verify with XOR8, SUM8 (mod 256) or "
            "CRC-8 variants before concluding; do not assume any fixed byte."
        ),
        extra_guidance=(
            "The target vehicle is NOT specified. Do not invent make/model "
            "specific conventions; infer signal layouts strictly from the "
            "observed byte statistics and frame timing."
        ),
    ),
    "hyundai_kia": VehiclePack(
        name="hyundai_kia",
        label="Hyundai / Kia",
        vehicle="Hyundai Kona",
        bus_speed_kbps=500,
        byte_order="little-endian",
        counter_notes=(
            "Many signals use rolling counters in the upper nibble of byte 0."
        ),
        checksum_notes=(
            "Checksums are often located in byte 7; reference "
            "hyundai_kia_generic.dbc patterns."
        ),
        extra_guidance="",
    ),
}


def _pack_dir() -> Path:
    """Directory hosting the JSON mirror of the builtin packs."""
    return Path(__file__).resolve().parent.parent / "vehicle_packs"


def load_all_packs(user_dir: str | None = None) -> dict[str, VehiclePack]:
    """Return name→pack, merging user JSON packs over the builtin defaults.

    Builtin packs come from the in-code defaults (already complete), then any
    ``*.json`` under ``canlab/vehicle_packs/`` and the optional ``user_dir``
    override the matching fields. Unknown pack names are appended.
    """
    packs = {name: VehiclePack(**asdict(pack)) for name, pack in _BUILTIN_PACKS.items()}

    def _merge_from(present: dict) -> None:
        for name, vp in present.items():
            merged = packs.get(name)
            if merged is None:
                packs[name] = vp
                continue
            for key, val in asdict(vp).items():
                if val is not None and val != "":
                    setattr(merged, key, val)

    _merge_from(_load_json_dir(_pack_dir()))
    if user_dir:
        _merge_from(_load_json_dir(Path(user_dir)))
    return packs


def _load_json_dir(directory: Path) -> dict[str, VehiclePack]:
    found: dict[str, VehiclePack] = {}
    if not directory.is_dir():
        return found
    for json_file in sorted(directory.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "name" not in data:
            continue
        allowed = {f for f in asdict(VehiclePack("x")).keys()}
        found[data["name"]] = VehiclePack(
            **{k: v for k, v in data.items() if k in allowed}
        )
    return found


def get_pack(name: str | VehiclePack | None) -> VehiclePack:
    """Resolve a pack reference; unknown/empty names fall back to generic."""
    if isinstance(name, VehiclePack):
        return name
    key = (name or "").strip().lower()
    return _BUILTIN_PACKS.get(key, _load_all_safe().get(key, _BUILTIN_PACKS["generic"]))


_cache_packs = None


def _load_all_safe() -> dict[str, VehiclePack]:
    global _cache_packs
    if _cache_packs is None:
        _cache_packs = load_all_packs()
    return _cache_packs


def build_system_prompt(pack: str | VehiclePack | None = None,
                        language: str = "English") -> str:
    """Assemble the AI engine system prompt from a vehicle knowledge pack.

    ``language`` controls the language used for framing (R1.3 hook); default
    English preserves existing behavior.
    """
    vp = get_pack(pack)

    if language and str(language).strip().lower().startswith("zh"):
        head = (
            "你是一名资深的汽车 CAN 总线逆向工程师。根据给定的 CAN 帧数据"
            "识别并结构化解读其中信号。请用中文输出。"
        )
        order_labels = {
            "SIGNAL IDENTIFICATION": "信号识别",
            "BYTE MAPPING": "字节映射",
            "SCALING & UNITS": "缩放与单位",
            "CONFIDENCE (0-100%)": "置信度 (0-100%)",
            "RECOMMENDED DBC ENTRY": "建议的 DBC 条目",
        }
    else:
        head = (
            "You are an expert automotive CAN bus reverse engineer. "
            "Analyze CAN frame data and identify signals."
        )
        order_labels = {
            "SIGNAL IDENTIFICATION": "SIGNAL IDENTIFICATION",
            "BYTE MAPPING": "BYTE MAPPING",
            "SCALING & UNITS": "SCALING & UNITS",
            "CONFIDENCE (0-100%)": "CONFIDENCE (0-100%)",
            "RECOMMENDED DBC ENTRY": "RECOMMENDED DBC ENTRY",
        }

    lines = [head]

    context = []
    if vp.vehicle:
        context.append(f"The vehicle is a {vp.vehicle}.")
    context.append(
        f"Known bus characteristics: {vp.bus_speed_kbps} kbps, "
        f"{vp.byte_order} default."
    )
    if vp.counter_notes:
        context.append(vp.counter_notes)
    if vp.checksum_notes:
        context.append(vp.checksum_notes)
    if vp.extra_guidance:
        context.append(vp.extra_guidance)
    if context:
        lines.append(" ".join(context))

    lines.append(
        "Format your response with clear sections:\n"
        + "\n".join(order_labels.values())
    )
    return "\n\n".join(lines)
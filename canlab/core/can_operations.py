"""Headless one-shot CAN operations used by GUI and API workers."""
from __future__ import annotations

from typing import Any


def inject_once(bus: Any, arbitration_id: int, data: bytes,
                extended: bool = False):
    """Build and safely transmit one CAN frame."""
    import can
    from core.can_service import secure_bus

    message = can.Message(
        arbitration_id=int(arbitration_id),
        data=bytes(data),
        is_extended_id=bool(extended),
    )
    secure_bus(bus).send(message)
    return message


def clear_dtc(bus: Any, tx_id: int = 0x7DF, rx_id: int = 0x7E8,
              timeout: float = 1.0) -> bytes:
    """Clear all DTC groups and require the matching UDS positive response."""
    from core.isotp import ISOTPSession

    request = bytes([0x14, 0xFF, 0xFF, 0xFF])
    with ISOTPSession(bus, tx_id=tx_id, rx_id=rx_id) as session:
        payload = session.send(request, timeout=timeout)
    if payload is None:
        raise TimeoutError("Timed out waiting for ClearDiagnosticInformation response")
    if payload[:2] == bytes([0x7F, 0x14]):
        nrc = payload[2] if len(payload) > 2 else 0
        raise RuntimeError(f"ClearDiagnosticInformation rejected (NRC 0x{nrc:02X})")
    if not payload or payload[0] != 0x54:
        rendered = " ".join(f"{byte:02X}" for byte in payload)
        raise RuntimeError(f"Unexpected ClearDiagnosticInformation response: {rendered}")
    return payload

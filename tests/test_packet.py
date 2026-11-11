"""Regression coverage for native RM4 carrier headers and repeated RF payloads."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "rf_fan"
    / "packet.py"
)
_spec = importlib.util.spec_from_file_location("rf_fan_packet", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
packet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(packet)


def _microseconds(ticks: list[int]) -> list[int]:
    return [round(t * packet._TICK_US) for t in ticks]


def test_rm4_decode_skips_carrier_without_losing_initial_pulses() -> None:
    # 433920 kHz carrier, then four pulses: 13, 37, 256 and 223 ticks.
    capture = bytes.fromhex("b1c00a00009f06000d25000100df")
    timings, flags = packet.decode_broadlink_packet(capture)
    assert timings == _microseconds([13, -37, 256, -223])
    assert flags == 0xC0


def test_legacy_decode_keeps_first_pulse_and_repeat_count() -> None:
    capture = bytes.fromhex("b20306000d25000100df")
    timings, repeats = packet.decode_broadlink_packet(capture)
    assert timings == _microseconds([13, -37, 256, -223])
    assert repeats == 3


def test_rm4_encode_keeps_flags_carrier_and_repeats_payload() -> None:
    # The carrier is intentionally 433840, not the configured 433920 preset.
    capture = bytes.fromhex("b1c00800b09e06000d250ddf")
    timings = _microseconds([13, -37, 13, -223])
    encoded = packet.encode_rm4_packet(capture, timings, repeat_count=2)
    assert encoded == bytes.fromhex("b1c01000b09e06000d250ddf0d250ddf0d250ddf")


def test_rm4_encode_retains_extended_tick_counts() -> None:
    capture = bytes.fromhex("b1c00a00009f06000d25000100df")
    timings = _microseconds([13, -37, 256, -223])
    assert packet.encode_rm4_packet(capture, timings) == capture


def test_decode_ignores_bytes_beyond_declared_payload() -> None:
    capture = bytes.fromhex("b1c00a00009f06000d25000100df0d050000")
    assert packet.decode_broadlink_packet(capture)[0] == _microseconds([13, -37, 256, -223])


@pytest.mark.parametrize(
    "capture",
    [
        bytes.fromhex("b1c00400009f06"),  # incomplete carrier
        bytes.fromhex("b1c00300009f06"),  # payload cannot hold a carrier
        bytes.fromhex("b1c00900009f06000d2500"),  # missing extended-tick bytes
    ],
)
def test_decode_rejects_truncated_native_packets(capture: bytes) -> None:
    with pytest.raises(ValueError):
        packet.decode_broadlink_packet(capture)


def _packet_with_libraries(
    monkeypatch: pytest.MonkeyPatch, libraries: dict[str, float | None]
) -> types.ModuleType:
    """Load packet.py with stand-ins for the Broadlink libraries.

    ``libraries`` maps an import name to the TICK its ``remote`` module has, or
    to None for a library without one (broadlink 0.19). A library that is not
    named cannot be imported, whatever the environment has installed.
    """
    for name in ("broadlink_async", "broadlink"):
        library = remote = None
        if name in libraries:
            remote = types.ModuleType(f"{name}.remote")
            if libraries[name] is not None:
                remote.TICK = libraries[name]
            library = types.ModuleType(name)
            library.remote = remote
        monkeypatch.setitem(sys.modules, name, library)
        monkeypatch.setitem(sys.modules, f"{name}.remote", remote)
    spec = importlib.util.spec_from_file_location("rf_fan_packet_libraries", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("libraries", "tick"),
    [
        # Home Assistant 2026.10.2 and newer: broadlink-async.
        ({"broadlink_async": 8192 / 269}, 8192 / 269),
        # Both importable (rf_fan 1.1.0 pinned `broadlink`): core's comes first,
        # as in command.py and rf.py.
        ({"broadlink_async": 30.0, "broadlink": 31.0}, 30.0),
        # 2026.10.0 - 2026.10.1: python-broadlink 1.0, imported as `broadlink`.
        ({"broadlink": 8192 / 269}, 8192 / 269),
        # 2026.5 - 2026.9: broadlink 0.19 has no TICK; core encodes at 32.84 us.
        ({"broadlink": None}, 32.84),
        ({}, 32.84),
    ],
)
def test_tick_comes_from_the_library_core_uses(
    monkeypatch: pytest.MonkeyPatch,
    libraries: dict[str, float | None],
    tick: float,
) -> None:
    assert _packet_with_libraries(monkeypatch, libraries)._TICK_US == tick

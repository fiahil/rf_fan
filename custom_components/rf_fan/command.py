"""Build and send learned RF codes through the radio_frequency platform."""

from __future__ import annotations

from base64 import b64decode
import logging
from typing import Any

from rf_protocols import ModulationType, RadioFrequencyCommand

from homeassistant.components.radio_frequency import async_send_command
from homeassistant.core import HomeAssistant

from .mercator import clean_frame
from .rf import decode_broadlink_packet

_LOGGER = logging.getLogger(__name__)


class CapturedCommand(RadioFrequencyCommand):
    """A learned RF code, replayed as raw OOK timings.

    We subclass the stable, top-level ``rf_protocols.RadioFrequencyCommand`` (the
    same import Home Assistant core uses) and set the attributes the transmitter
    reads directly, rather than importing the library's internal command modules
    - their layout differs between rf_protocols releases (``commands`` is a
    module in the shipped version, a package on ``main``). The Broadlink
    transmitter only consumes ``frequency``, ``repeat_count`` and
    ``get_raw_timings()``; ``modulation`` gates the transmitter-support check.
    We deliberately skip ``super().__init__`` to stay immune to constructor
    changes across releases.
    """

    def __init__(
        self, *, frequency: int, timings: list[int], repeat_count: int = 0
    ) -> None:
        """Initialise from decoded raw timings."""
        self.frequency = frequency
        self.modulation = ModulationType.OOK
        self.repeat_count = repeat_count
        self.symbol_rate = None
        self.output_power = None
        self._timings = timings

    def get_raw_timings(self) -> list[int]:
        """Return the signed alternating microsecond timings."""
        return self._timings


# Drop leading/trailing gaps longer than this (microseconds). Direct captures can
# include tens of milliseconds (up to seconds) of idle before/after the real code;
# transmitting that desyncs some receivers - notably the Mercator FRM97 - and it
# isn't part of the signal. Real inter-frame gaps are well under this.
_IDLE_TRIM_US = 20000


def _trim_idle(timings: list[int]) -> list[int]:
    """Drop huge leading/trailing idle gaps from a captured pulse train."""
    ts = [int(t) for t in timings]
    while ts and abs(ts[0]) > _IDLE_TRIM_US:
        ts.pop(0)
    while ts and abs(ts[-1]) > _IDLE_TRIM_US:
        ts.pop()
    return ts


def _stored_timings(data: dict[str, Any]) -> list[int]:
    """Return a stored command's pulse train in microseconds at today's tick.

    The raw Broadlink packet (``b64``) is the capture's ground truth: it holds
    tick counts, and the transmitter re-quantises our microseconds back to
    ticks. ``timings`` were decoded with whatever tick was in force when the
    button was learned, and that tick changed in Home Assistant 2026.10 (32.84
    -> 30.45 us), so a capture learned before the upgrade would otherwise be
    replayed about 8% too slow. Re-decoding the packet keeps replays exact
    without re-learning. ``timings`` remain the fallback for entries without a
    packet.
    """
    if b64 := data.get("b64"):
        try:
            timings, _ = decode_broadlink_packet(b64decode(b64))
        except (ValueError, IndexError):
            _LOGGER.debug("rf_fan: stored packet undecodable, using stored timings")
        else:
            if timings:
                return timings
    return [int(t) for t in data["timings"]]


async def async_send_stored(
    hass: HomeAssistant,
    transmitter: str,
    data: dict[str, Any],
    frequency: int,
    *,
    clean: bool = False,
    repeat: int = 0,
) -> None:
    """Send a stored command dict (``{"b64", "timings"}``) via a transmitter.

    Normally we send the (idle-trimmed) captured train once - it already holds
    several frame repeats. With ``clean=True`` we instead send a single de-noised
    consensus frame, which the Broadlink repeats ``repeat`` times: needed for
    fussy remotes (e.g. Mercator FRM97) whose raw captures contain noisy frames.
    The clean frame carries the inter-frame gap measured in the capture, since
    receivers need their own gap length to re-synchronise between repeats.
    """
    raw = _stored_timings(data)
    if clean:
        timings = clean_frame(raw) or _trim_idle(raw)
    else:
        timings = _trim_idle(raw)
    _LOGGER.debug(
        "rf_fan: sending %d pulses via %s (clean=%s, repeat=%d, trailing gap=%d us)",
        len(timings),
        transmitter,
        clean,
        repeat,
        timings[-1] if timings else 0,
    )
    command = CapturedCommand(
        frequency=frequency, timings=timings, repeat_count=repeat
    )
    await async_send_command(hass, transmitter, command)

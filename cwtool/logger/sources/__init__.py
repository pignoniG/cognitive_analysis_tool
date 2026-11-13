"""Sensor sources. Hardware libraries are imported when a source is opened, so a missing one only affects
that source."""

from cwtool.logger.sources.lux import LuxSerialSource, list_ports
from cwtool.logger.sources.lsl import LslSource, discover_devices, discover_streams
from cwtool.logger.sources.shimmer import ShimmerSource
from cwtool.logger.sources.simulated import SimulatedSource
from cwtool.logger.sources.spectral import SpectralSerialSource

__all__ = ["LuxSerialSource", "LslSource", "ShimmerSource", "SimulatedSource", "SpectralSerialSource", "discover_devices",
           "discover_streams", "list_ports"]

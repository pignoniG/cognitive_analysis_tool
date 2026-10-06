"""Sensor sources. Hardware libraries are imported when a source is opened, so a missing one only affects
that source."""

from cwtool.logger.sources.lux import LuxSerialSource, list_ports
from cwtool.logger.sources.lsl import LslSource, discover_streams
from cwtool.logger.sources.shimmer import ShimmerSource
from cwtool.logger.sources.simulated import SimulatedSource

__all__ = ["LuxSerialSource", "LslSource", "ShimmerSource", "SimulatedSource", "discover_streams", "list_ports"]

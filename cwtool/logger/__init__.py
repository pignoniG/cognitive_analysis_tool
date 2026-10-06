"""Multi-sensor logger: lux sensor, Shimmer ECG and EmotiBit recorded side by side on the computer's clock.

The classes here do not import Qt; the window is in :mod:`cwtool.logger.gui` (``cwtool-logger``).
"""

from cwtool.logger.base import ClockMapper, Source
from cwtool.logger.session import EventLog, Logger

__all__ = ["ClockMapper", "EventLog", "Logger", "Source"]

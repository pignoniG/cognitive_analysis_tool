"""Cognitive workload analysis tool, version 2.

Core library for luminance-compensated pupillometry. It is independent of
any GUI: load a recording with :func:`cwtool.devices.load`, analyse its scene
video with :func:`cwtool.video.analyse_video` and run
:func:`cwtool.pipeline.run` with a set of :class:`cwtool.params.Parameters`.
"""

__version__ = "2.0.0.dev0"

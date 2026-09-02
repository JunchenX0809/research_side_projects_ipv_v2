"""Standalone MAIAC AOD exposure pipeline.

This package intentionally does not import the MODIS burned-area, FIRMS, FRP, or
VIIRS product exporters. It only reuses product-neutral survey-date and GADM
normalization helpers.
"""

from .manifest import AodJob, load_manifest

__all__ = ["AodJob", "load_manifest"]

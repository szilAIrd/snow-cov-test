"""
Real FSC (Fractional Snow Cover) data provider.

This module queries Copernicus HR-WSI products from the public S3 bucket.
No mock/synthetic fallback is used. If real data is unavailable for a point,
the provider returns no-data (205) for that point.

FSC pixel encoding (CLMS HR-WSI spec):
    0 – 100  fractional snow cover percentage
    205      cloud-obscured / no data
    210      water body
    255      confirmed snow-free (low NDSI)
"""

import logging
import math
import os
from datetime import date
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real-data configuration
# ---------------------------------------------------------------------------
_USE_REAL   = True
_CACHE_DIR  = os.getenv("FSC_CACHE_DIR", "/tmp/fsc_cache")
_PROD_TYPE  = os.getenv("FSC_PRODUCT_TYPE", "GFSC")
# Search window used when querying S3; generous so we find even sparse tiles.
_S3_MAX_AGE = 14

log.info(
    "FSC provider mode: %s  (product=%s, cache=%s)",
    "REAL DATA ONLY (Copernicus S3)",
    _PROD_TYPE,
    _CACHE_DIR,
)


def get_fsc_value(
    lat: float,
    lon: float,
    elevation_m: Optional[float],
    analysis_date: date,
) -> Tuple[int, date]:
    """
    Return (fsc_value, acquisition_date) for a single route point.

    The value is sampled from a real Copernicus CLMS HR-WSI GeoTIFF downloaded
    from the public S3 bucket. If no suitable product is found or retrieval
    fails, returns no-data (205) for this point.
    """
    try:
        from . import fsc_s3
        tile = fsc_s3.get_mgrs_tile(lat, lon)
        result = fsc_s3.find_product_key(
            tile,
            analysis_date.isoformat(),
            _PROD_TYPE,
            _S3_MAX_AGE,
        )
        if result is None:
            log.warning(
                "No %s product found on S3 for tile %s within %d days of %s. "
                "Returning no-data (205).",
                _PROD_TYPE, tile, _S3_MAX_AGE, analysis_date.isoformat(),
            )
            return 205, analysis_date

        s3_key, actual_date_iso = result
        tiff_path = fsc_s3.get_cached_tiff(s3_key, _CACHE_DIR)
        if tiff_path is not None:
            fsc = fsc_s3.sample_pixel(tiff_path, lat, lon)
            collector = fsc_s3.get_active_trace_collector()
            if collector is not None:
                collector.record_used(s3_key)
            return fsc, date.fromisoformat(actual_date_iso)

        log.warning(
            "Download failed for %s. Returning no-data (205).",
            s3_key,
        )
        return 205, analysis_date
    except Exception as exc:
        log.warning(
            "Real FSC lookup failed at (%.4f, %.4f): %s. Returning no-data (205).",
            lat, lon, exc,
        )
        return 205, analysis_date


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def compute_slope(
    lat1: float, lon1: float, elev1: Optional[float],
    lat2: float, lon2: float, elev2: Optional[float],
) -> float:
    """Return terrain slope angle in degrees between two GPS points.

    Falls back to a plausible moderate slope (12°) if elevation data
    is absent.
    """
    if elev1 is None or elev2 is None:
        return 12.0

    dist = haversine_m(lat1, lon1, lat2, lon2)
    if dist < 1.0:
        return 0.0

    elev_diff = abs(elev2 - elev1)
    return math.degrees(math.atan2(elev_diff, dist))

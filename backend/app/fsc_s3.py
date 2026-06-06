"""
Copernicus CLMS HR-WSI S3 data access.

Provides functions to query and download Fractional Snow Cover (FSC / GFSC)
products from the public CLMS S3 bucket, then sample FSC pixel values at
WGS-84 coordinates.

S3 endpoint:  https://s3.WAW3-2.cloudferro.com
Bucket:       HRWSI
Key format:   {productType}/{tile}/{year}/{month}/{day}/{productDir}/{layers}

Credentials are the public service credentials published in the official
CLMS HR-WSI Python client (no personal account required):
  https://github.com/eea/clms-hrwsi-api-client-python

FSC pixel encoding (CLMS HR-WSI spec):
  0 – 100   fractional snow cover %
  205       cloud-obscured (only in non-gap-filled FSC)
  210       inland water
  255       snow-free / confirmed clear
"""

import logging
import threading
from contextvars import ContextVar, Token
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import boto3
import mgrs as _mgrs_module
import rasterio
from botocore.config import Config
from pyproj import Transformer
from rasterio.windows import Window

from .copernicus_trace import CopernicusTraceCollector

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public S3 credentials (CLMS service account — no personal login needed)
# ---------------------------------------------------------------------------
_ENDPOINT   = "https://s3.WAW3-2.cloudferro.com"
_ACCESS_KEY = "c4ae60af7b144053803c618a8860f7c9"
_SECRET_KEY = "dcb3ba1f6eab45aaaec5802feef5e2e4"
_BUCKET     = "HRWSI"

# Layer suffixes tried in preference order.
# V2+ products (CLMS V102, since ~2025) use _GF.tif for the gap-filled FSC layer.
# Older V1 products used _FSCOG.tif / _FSC_OG.tif / _FSC.tif.
_FSCOG_SUFFIXES = ("_GF.tif", "_FSCOG.tif", "_FSC_OG.tif", "_FSC.tif")

# Substrings that identify non-FSC layers — excluded from the last-resort pick.
# _AT   = Acquisition Time layer
# _GF-QA = Gap-Filled quality layer
# QAFLAGS / QCFLAGS = QA flag layers
_SKIP_PATTERNS = ("QAFLAGS", "QCFLAGS", "FSCTOC", "NDSI", "_CC", "_SWS", "_WDS", "_WIC", "_AT.tif", "_GF-QA")

# ---------------------------------------------------------------------------
# MGRS tile-ID converter
# ---------------------------------------------------------------------------
_mgrs_conv = _mgrs_module.MGRS()


def get_mgrs_tile(lat: float, lon: float) -> str:
    """Convert a WGS-84 coordinate to a 5-char MGRS tile ID (e.g. ``'32TPT'``).

    ``MGRSPrecision=0`` returns only the Grid Zone Designator (2 digits +
    1 band letter) plus the 100 km square identifier (2 letters), yielding
    5 characters that match the folder names in the CLMS S3 bucket.
    """
    return _mgrs_conv.toMGRS(lat, lon, MGRSPrecision=0)


# ---------------------------------------------------------------------------
# S3 client (lazy — avoids import-time network activity)
# ---------------------------------------------------------------------------
_s3_client: Optional[object] = None
_s3_lock = threading.Lock()
_trace_collector: ContextVar[Optional[CopernicusTraceCollector]] = ContextVar(
    "copernicus_trace_collector", default=None
)


def set_trace_collector(collector: CopernicusTraceCollector) -> Token:
    return _trace_collector.set(collector)


def reset_trace_collector(token: Token) -> None:
    _trace_collector.reset(token)


def get_active_trace_collector() -> Optional[CopernicusTraceCollector]:
    return _trace_collector.get()


def _client():
    global _s3_client
    if _s3_client is None:
        with _s3_lock:
            if _s3_client is None:
                # response_checksum_validation suppresses noisy warnings
                # introduced by a botocore regression (botocore issue #3382).
                try:
                    cfg = Config(response_checksum_validation="when_required")
                except TypeError:
                    cfg = Config()
                _s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=_ACCESS_KEY,
                    aws_secret_access_key=_SECRET_KEY,
                    endpoint_url=_ENDPOINT,
                    config=cfg,
                )
    return _s3_client


# ---------------------------------------------------------------------------
# Product discovery
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def find_product_key(
    tile: str,
    target_date_iso: str,
    product_type: str = "GFSC",
    max_age_days: int = 14,
) -> Optional[Tuple[str, str]]:
    """Find the S3 key of the on-ground FSC layer nearest to *target_date*.

    Walks backwards day-by-day from *target_date* (up to *max_age_days*),
    listing objects under ``{productType}/{tile}/{year}/{mm}/{dd}/``.
    Returns ``(s3_key, actual_date_iso)`` for the most recent available
    product, or ``None`` if nothing is found within the search window.

    Results are LRU-cached (512 entries) so repeated calls for the same
    tile × date do not re-query S3.
    """
    target = date.fromisoformat(target_date_iso)
    for delta in range(max_age_days + 1):
        d = target - timedelta(days=delta)
        prefix = (
            f"{product_type}/{tile}/"
            f"{d.year}/{d.month:02d}/{d.day:02d}/"
        )
        try:
            resp = _client().list_objects_v2(
                Bucket=_BUCKET,
                Prefix=prefix,
                MaxKeys=30,
            )
        except Exception as exc:
            # A connection-level error means all subsequent days will also fail;
            # bail out immediately rather than hammering a dead endpoint 14 times.
            log.error(
                "S3 connection error — cannot reach %s (prefix=%s): %s. "
                "Check network access and endpoint URL.",
                _ENDPOINT, prefix, exc,
            )
            return None

        keys = [obj["Key"] for obj in resp.get("Contents", [])]
        key = _pick_fsc_key(keys)
        if key:
            collector = get_active_trace_collector()
            if collector is not None:
                collector.record_queried(key)
            log.info("FSC product found: %s (-%d day offset from %s)", key, delta, target_date_iso)
            return key, d.isoformat()

    log.warning(
        "No %s product found for tile %s in the %d days before %s.",
        product_type, tile, max_age_days, target_date_iso,
    )
    return None


def _pick_fsc_key(keys: list) -> Optional[str]:
    """Select the best on-ground FSC layer from a list of S3 object keys."""
    for suffix in _FSCOG_SUFFIXES:
        for key in keys:
            if key.endswith(suffix):
                return key
    # Last resort: any .tif not matching quality/other-band patterns
    for key in keys:
        if key.endswith(".tif") and not any(p in key for p in _SKIP_PATTERNS):
            return key
    return None


def list_available_dates_for_month(
    tile: str,
    year: int,
    month: int,
    product_type: str = "GFSC",
) -> list:
    """Return sorted list of ISO date strings that have products in S3 for a tile/month.

    Uses a single ``list_objects_v2`` call with a month-level prefix and
    ``Delimiter="/"`` to enumerate the day sub-folders — much cheaper than
    performing up to 31 individual day-level queries.
    """
    prefix = f"{product_type}/{tile}/{year}/{month:02d}/"
    try:
        resp = _client().list_objects_v2(
            Bucket=_BUCKET,
            Prefix=prefix,
            Delimiter="/",
            MaxKeys=50,  # at most 31 days + safety margin
        )
    except Exception as exc:
        log.error(
            "S3 month-listing failed for tile %s %d/%02d: %s",
            tile, year, month, exc,
        )
        return []

    dates = []
    for cp in resp.get("CommonPrefixes", []):
        # Each CommonPrefix looks like "GFSC/32TLR/2025/01/15/"
        day_str = cp["Prefix"].rstrip("/").split("/")[-1]
        try:
            d = date(year, month, int(day_str))
            dates.append(d.isoformat())
        except (ValueError, IndexError):
            pass
    return sorted(dates)


# ---------------------------------------------------------------------------
# Download to local disk cache
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def get_cached_tiff(s3_key: str, cache_dir: str) -> Optional[Path]:
    """Download *s3_key* to *cache_dir* and return the local ``Path``.

    Skips the download if the file already exists (disk-cache hit).
    Returns ``None`` if the download fails.  Incomplete files are removed
    so a retry on the next request starts clean.
    """
    filename = Path(s3_key).name
    local = Path(cache_dir) / filename
    if local.exists():
        log.debug("Disk cache hit: %s", local)
        return local

    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        log.info("Downloading s3://%s/%s → %s", _BUCKET, s3_key, local)
        _client().download_file(_BUCKET, s3_key, str(local))
        collector = get_active_trace_collector()
        if collector is not None:
            collector.record_downloaded(s3_key)
        log.info("Download complete: %s (%.1f MB)", local.name, local.stat().st_size / 1e6)
        return local
    except Exception as exc:
        log.warning("Download failed for %s: %s", s3_key, exc)
        try:
            local.unlink()
        except FileNotFoundError:
            pass
        return None


# ---------------------------------------------------------------------------
# Pixel sampling
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _get_transformer(crs_wkt: str) -> Transformer:
    """Return a cached WGS-84 → tile-UTM ``Transformer`` for *crs_wkt*."""
    return Transformer.from_crs("EPSG:4326", crs_wkt, always_xy=True)


def sample_pixel(tiff_path: Path, lat: float, lon: float) -> int:
    """Read the FSC pixel value at (lat, lon) from a local CLMS GeoTIFF.

    The raster is in a UTM projection; the WGS-84 coordinate is reprojected
    on the fly using a cached ``pyproj.Transformer``.  Returns ``255``
    (snow-free) if the point falls outside the tile footprint.

    CLMS FSC encoding:
        0 – 100   fractional snow cover %
        205       cloud-obscured (FSC only; GFSC has this gap-filled)
        210       inland water
        255       snow-free / confirmed clear
    """
    with rasterio.open(tiff_path) as ds:
        t = _get_transformer(ds.crs.to_wkt())
        x, y = t.transform(lon, lat)

        try:
            row, col = ds.index(x, y)
        except Exception:
            return 255  # coordinate outside this tile

        if row < 0 or col < 0 or row >= ds.height or col >= ds.width:
            return 255

        data = ds.read(1, window=Window(col, row, 1, 1))
        raw = int(data[0, 0])

    # Treat out-of-range fill values as snow-free
    if raw < 0 or raw > 255:
        return 255
    return raw

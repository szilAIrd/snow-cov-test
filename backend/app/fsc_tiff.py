"""
Real Copernicus HR-WSI FSC tile renderer.

Reads actual CLMS_WSI_FSC GeoTIFF files (NDSI single-band, 20 m resolution,
EPSG:32632 / UTM 32N) and renders them as 256×256 RGBA PNG tiles in the XYZ
scheme (EPSG:4326 / WGS-84 output).

This is identical in spirit to the _tiff_to_overlay() and _classify_route()
functions in interactive_map.py — just split into per-tile requests instead
of a single full-image export, so MapLibre can stream them as a raster layer.

CLMS NDSI encoding (HR-WSI Product User Manual §5.3):
    0 – 100   fractional snow cover % (NDSI-derived)
    205       cloud or cloud shadow
    210       inland water
    255       snow-free / no data

Environment:
    FSC_DATA_DIR   directory to scan for CLMS GeoTIFF files.
                   Default: <this file>/../../../../snow-coverage
                   (i.e. the sibling repo that holds the real .tif files)
"""

import io
import math
import os
import re
from datetime import date as _date
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject as rio_reproject, transform_bounds
from PIL import Image

# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _default_data_dir() -> Path:
    """
    Walk up from this file to find the sibling snow-coverage repo, which is
    where the real CLMS GeoTIFFs live.  Override with FSC_DATA_DIR env var.
    """
    env = os.environ.get("FSC_DATA_DIR")
    if env:
        return Path(env)
    # <repo>/backend/app/fsc_tiff.py → <repo>/.. → snow-coverage
    here = Path(__file__).resolve()
    sibling = here.parent.parent.parent.parent / "snow-coverage"
    return sibling


_DATA_DIR = _default_data_dir()
_TIFF_GLOB = "CLMS_WSI_FSC_020m_*.tif"

# Pre-load: list of (path, lon_min, lat_min, lon_max, lat_max)
# indexed once at import time so tile requests don't re-stat the filesystem.
_TIFF_INDEX: list[tuple[Path, float, float, float, float]] = []


def _build_index() -> list[tuple[Path, float, float, float, float]]:
    index = []
    if not _DATA_DIR.exists():
        return index
    for p in sorted(_DATA_DIR.glob(_TIFF_GLOB)):
        try:
            with rasterio.open(p) as ds:
                lon_min, lat_min, lon_max, lat_max = transform_bounds(
                    ds.crs, "EPSG:4326", *ds.bounds
                )
            index.append((p, lon_min, lat_min, lon_max, lat_max))
        except Exception:
            continue
    return index


_TIFF_INDEX = _build_index()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def available() -> bool:
    """True when at least one CLMS GeoTIFF has been found on disk."""
    return len(_TIFF_INDEX) > 0


def coverage_info() -> dict:
    """
    Return metadata about all indexed GeoTIFF files.

    {
        "available": bool,
        "file_count": int,
        "date": "YYYY-MM-DD" | null,   # acquisition date from filename
        "lon_min": float, "lat_min": float, "lon_max": float, "lat_max": float,
        "files": [{"name": str, "lon_min": ..., ...}, ...]
    }
    """
    if not _TIFF_INDEX:
        return {"available": False, "file_count": 0, "date": None,
                "lon_min": None, "lat_min": None, "lon_max": None, "lat_max": None,
                "files": []}

    # Extract acquisition date from filename:
    # CLMS_WSI_FSC_020m_T32TNS_20260522T102815_S2A_V200_NDSI.tif
    #                         ^^^^^^^^
    import re
    date_str = None
    m = re.search(r"_(\d{8})T", _TIFF_INDEX[0][0].name)
    if m:
        raw = m.group(1)
        date_str = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    lon_min = min(t[1] for t in _TIFF_INDEX)
    lat_min = min(t[2] for t in _TIFF_INDEX)
    lon_max = max(t[3] for t in _TIFF_INDEX)
    lat_max = max(t[4] for t in _TIFF_INDEX)

    return {
        "available": True,
        "file_count": len(_TIFF_INDEX),
        "date": date_str,
        "lon_min": round(lon_min, 4),
        "lat_min": round(lat_min, 4),
        "lon_max": round(lon_max, 4),
        "lat_max": round(lat_max, 4),
        "files": [
            {
                "name": t[0].name,
                "lon_min": round(t[1], 4), "lat_min": round(t[2], 4),
                "lon_max": round(t[3], 4), "lat_max": round(t[4], 4),
            }
            for t in _TIFF_INDEX
        ],
    }


# ---------------------------------------------------------------------------
# Colour mapping — direct port of _fsc_to_rgba from interactive_map.py,
# adapted so snow-free (255) and water (210) are transparent for overlay use.
# ---------------------------------------------------------------------------

_NODATA_SENTINEL = 254  # fills pixels outside every TIFF's extent


def _fsc_to_rgba_overlay(band: np.ndarray) -> np.ndarray:
    """
    Convert CLMS FSC NDSI values to an RGBA overlay image.

    Snow-free (255) → transparent so the OSM base map shows terrain.
    Water (210)     → transparent (OSM already renders water correctly).
    Outside TIFF (254 sentinel) → transparent.
    Cloud (205)     → semi-transparent steel-grey.
    Snow (0-100)    → vivid cornflower-blue → ice-white gradient, high opacity.
                      Alpha *increases* with coverage so heavier snow is more
                      visible. The vivid blue base colour stands out strongly
                      against the green/brown/grey tones of the topographic
                      base map.
    """
    h, w = band.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    # Snow (0-100): vivid blue (#2878FF) → ice white, opacity 73 % → 90 %
    snow = (band >= 0) & (band <= 100)
    if snow.any():
        frac = band[snow].astype(np.float32) / 100.0
        rgba[snow, 0] = np.clip( 40 + frac * 215, 0, 255).astype(np.uint8)  #  40 → 255
        rgba[snow, 1] = np.clip(120 + frac * 135, 0, 255).astype(np.uint8)  # 120 → 255
        rgba[snow, 2] = 255                                                    # constant
        rgba[snow, 3] = np.clip(185 + frac *  45, 0, 255).astype(np.uint8)  # 185 → 230

    # Cloud (205) → steel-grey, clearly distinct from snow
    rgba[band == 205] = (150, 160, 170, 130)

    # Snow-free (255), water (210), outside (254) → fully transparent (zeros)
    # Array is already zeroed.

    return rgba


# ---------------------------------------------------------------------------
# Tile renderer
# ---------------------------------------------------------------------------

def _tile_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return (lon_min, lat_min, lon_max, lat_max) in WGS-84 for an XYZ tile."""
    n = 1 << z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def render_tile(z: int, x: int, y: int) -> Optional[bytes]:
    """
    Render a 256×256 RGBA PNG tile from real CLMS FSC GeoTIFF files.

    Returns None if no indexed TIFF overlaps with this tile.

    Algorithm:
        1. Compute tile WGS-84 bounding box.
        2. For every TIFF whose extent overlaps the tile:
           a. Reproject its NDSI band into a 256×256 WGS-84 grid matching
              the tile bbox, using nearest-neighbour resampling to preserve
              the discrete FSC / cloud / water encoding.
           b. Composite into result (first valid pixel wins; this handles the
              small overlap between adjacent MGRS tiles cleanly).
        3. Apply CLMS colour mapping → RGBA.
        4. Encode as PNG and return.
    """
    if not _TIFF_INDEX:
        return None

    lon_min, lat_min, lon_max, lat_max = _tile_bbox(z, x, y)

    # Find overlapping TIFFs
    overlapping = [
        entry for entry in _TIFF_INDEX
        if not (lon_max <= entry[1] or lon_min >= entry[3] or
                lat_max <= entry[2] or lat_min >= entry[4])
    ]
    if not overlapping:
        return None

    TILE = 256
    dst_transform = from_bounds(lon_min, lat_min, lon_max, lat_max, TILE, TILE)

    # Fill with sentinel; covered pixels will be written with real values
    result = np.full((TILE, TILE), _NODATA_SENTINEL, dtype=np.uint8)

    for path, *_ in overlapping:
        dst_band = np.full((TILE, TILE), _NODATA_SENTINEL, dtype=np.uint8)
        with rasterio.open(path) as ds:
            # Read raw data (don't mask, we want all values including 255)
            src_data = ds.read(1, masked=False)
            rio_reproject(
                source=src_data,
                destination=dst_band,
                src_transform=ds.transform,
                src_crs=ds.crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.nearest,
                src_nodata=None,     # treat every source value as valid
                dst_nodata=_NODATA_SENTINEL,
            )

        # Composite: first valid pixel wins
        valid = dst_band != _NODATA_SENTINEL
        result[valid & (result == _NODATA_SENTINEL)] = dst_band[valid & (result == _NODATA_SENTINEL)]

    rgba = _fsc_to_rgba_overlay(result)
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Cache-based tile renderer  (serves real Copernicus _GF.tif files from the
# S3 disk cache written by fsc_s3.get_cached_tiff)
# ---------------------------------------------------------------------------

# Pre-rendered fully-transparent tile for requests that have no coverage.
_TRANSPARENT_TILE: bytes = (lambda: (
    lambda buf: (Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, format="PNG"), buf.getvalue())[1]
)(io.BytesIO()))()


@lru_cache(maxsize=256)
def _cached_tiff_bounds(path_str: str) -> tuple:
    """Return (lon_min, lat_min, lon_max, lat_max) in WGS-84 for a GeoTIFF.

    Results are cached by file path so the expensive rasterio open is only
    done once per file across all tile requests.
    """
    with rasterio.open(path_str) as ds:
        return tuple(transform_bounds(ds.crs, "EPSG:4326", *ds.bounds))


def _index_for_date(
    cache_dir: str, date_iso: str, max_age_days: int = 14
) -> list[tuple]:
    """Scan *cache_dir* for ``*_GF.tif`` files whose date falls within
    *max_age_days* before *date_iso* (inclusive).

    Using a date-range match (instead of exact string match) means that if
    the user selects a date with no direct coverage, the most-recent cached
    file for the area is still returned — matching the behaviour of
    :func:`fsc_s3.find_product_key`.

    Returns a list of ``(path, lon_min, lat_min, lon_max, lat_max)`` tuples.
    """
    p = Path(cache_dir)
    if not p.exists():
        return []
    target = _date.fromisoformat(date_iso)
    index = []
    for f in sorted(p.glob("*_GF.tif")):
        m = re.search(r'_(\d{8})P', f.name)
        if not m:
            continue
        raw = m.group(1)
        try:
            file_date = _date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            continue
        delta = (target - file_date).days
        if not (0 <= delta <= max_age_days):
            continue
        try:
            bounds = _cached_tiff_bounds(str(f))
            index.append((f, *bounds))
        except Exception:
            pass
    return index


def _fetch_mgrs_for_bbox(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
    date_iso: str, cache_dir: str, product_type: str, max_age_days: int,
) -> None:
    """Download missing Copernicus GeoTIFFs from S3 for the given bbox/date.

    Samples a 3×3 grid of points within the tile bbox, resolves each to its
    MGRS tile ID, and downloads the matching ``*_GF.tif`` from S3 if not
    already on disk.  Both :func:`fsc_s3.find_product_key` and
    :func:`fsc_s3.get_cached_tiff` are LRU-cached, so repeated calls for
    the same MGRS tile within a session are near-instant.
    """
    from . import fsc_s3  # lazy import to avoid circular dependency

    seen: set = set()
    for lat_f in (0.25, 0.5, 0.75):
        for lon_f in (0.25, 0.5, 0.75):
            lat = lat_min + lat_f * (lat_max - lat_min)
            lon = lon_min + lon_f * (lon_max - lon_min)
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            try:
                tile_id = fsc_s3.get_mgrs_tile(lat, lon)
            except Exception:
                continue
            if tile_id in seen:
                continue
            seen.add(tile_id)
            try:
                result = fsc_s3.find_product_key(
                    tile_id, date_iso, product_type, max_age_days
                )
                if result is not None:
                    fsc_s3.get_cached_tiff(result[0], cache_dir)
            except Exception:
                pass


def render_tile_from_cache(
    z: int,
    x: int,
    y: int,
    cache_dir: str,
    date_iso: str,
    product_type: str = "GFSC",
    max_age_days: int = 14,
) -> bytes:
    """Render a 256×256 RGBA PNG tile from cached Copernicus *_GF.tif* files.

    Scans *cache_dir* for ``*_GF.tif`` files whose date falls within
    *max_age_days* before *date_iso*, reprojects overlapping raster windows
    into the requested XYZ tile bbox, and returns a PNG.

    If no cached file covers the tile **and** ``z >= 6``, triggers an
    on-demand download from the Copernicus S3 bucket before rendering.
    Returns a fully-transparent 256×256 PNG if no data is available.
    """
    lon_min, lat_min, lon_max, lat_max = _tile_bbox(z, x, y)

    index = _index_for_date(cache_dir, date_iso, max_age_days)

    def _overlapping(idx):
        return [
            entry for entry in idx
            if not (
                lon_max <= entry[1] or lon_min >= entry[3]
                or lat_max <= entry[2] or lat_min >= entry[4]
            )
        ]

    overlapping = _overlapping(index)

    # On-demand S3 fetch when nothing is cached for this area (z >= 6 guard
    # prevents fetching hundreds of MGRS tiles at very low zoom levels).
    if not overlapping and z >= 6:
        _fetch_mgrs_for_bbox(
            lon_min, lat_min, lon_max, lat_max,
            date_iso, cache_dir, product_type, max_age_days,
        )
        # Rebuild index to include any newly downloaded files.
        index = _index_for_date(cache_dir, date_iso, max_age_days)
        overlapping = _overlapping(index)

    if not overlapping:
        return _TRANSPARENT_TILE

    TILE = 256
    dst_transform = from_bounds(lon_min, lat_min, lon_max, lat_max, TILE, TILE)
    canvas = np.full((TILE, TILE), _NODATA_SENTINEL, dtype=np.uint8)

    for path, *_ in overlapping:
        dst_band = np.full((TILE, TILE), _NODATA_SENTINEL, dtype=np.uint8)
        with rasterio.open(path) as ds:
            # Use a windowed read so we only pull the data needed for this
            # tile rather than loading the entire (potentially large) raster.
            from rasterio.windows import from_bounds as _win_from_bounds
            from pyproj import Transformer as _Transformer

            # Transform tile WGS-84 bbox corners into the source CRS.
            xformer = _Transformer.from_crs(
                "EPSG:4326", ds.crs, always_xy=True
            )
            xs, ys = xformer.transform(
                [lon_min, lon_max, lon_min, lon_max],
                [lat_min, lat_min, lat_max, lat_max],
            )
            src_left, src_right = min(xs), max(xs)
            src_bottom, src_top = min(ys), max(ys)

            win = _win_from_bounds(
                src_left, src_bottom, src_right, src_top, ds.transform
            )
            # Expand by 2 px on each side to avoid reprojection edge gaps.
            win = rasterio.windows.Window(
                max(0, int(win.col_off) - 2),
                max(0, int(win.row_off) - 2),
                min(ds.width  - max(0, int(win.col_off) - 2),
                    int(win.width)  + 4),
                min(ds.height - max(0, int(win.row_off) - 2),
                    int(win.height) + 4),
            )
            if win.width <= 0 or win.height <= 0:
                continue

            src_data = ds.read(1, window=win, masked=False)
            src_transform = ds.window_transform(win)

        rio_reproject(
            source=src_data,
            destination=dst_band,
            src_transform=src_transform,
            src_crs=ds.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
            src_nodata=None,
            dst_nodata=_NODATA_SENTINEL,
        )

        valid = dst_band != _NODATA_SENTINEL
        canvas[valid & (canvas == _NODATA_SENTINEL)] = dst_band[
            valid & (canvas == _NODATA_SENTINEL)
        ]

    rgba = _fsc_to_rgba_overlay(canvas)
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

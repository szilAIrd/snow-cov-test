"""
FSC raster tile generator (XYZ scheme, 256 × 256 RGBA PNG).

Mimics what the production tile server would produce from real Copernicus
HR-WSI FSCOG GeoTIFFs stored in PostGIS/COG object storage (DesignDoc §9.4).
Replace render_fsc_tile() with a PostGIS/TiTiler query when live data is
available.

Colour convention (matches Copernicus HR-WSI FSC encoding):
  FSC 0 – 100  →  blue (#3b82f6) to white (#ffffff) gradient
  FSC 205      →  light grey  (cloud-obscured pixel)
  FSC 255      →  transparent (confirmed snow-free)
"""

import io
import math
from datetime import date
from typing import Optional

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Elevation model
# Combine Alpine/global mountain peaks with sea-level anchors so IDW gives
# plausible elevations everywhere on the globe.
# ---------------------------------------------------------------------------

# (lat_deg, lon_deg, elevation_m)
_PEAKS: list[tuple[float, float, float]] = [
    # --- European Alps ---
    (45.83,  6.87, 4808),  # Mont Blanc
    (45.94,  7.87, 4634),  # Monte Rosa / Dufourspitze
    (46.09,  7.86, 4545),  # Dom
    (45.98,  7.66, 4478),  # Matterhorn
    (46.10,  7.72, 4506),  # Weisshorn
    (45.94,  7.28, 4314),  # Grand Combin
    (46.54,  8.13, 4274),  # Finsteraarhorn
    (46.54,  7.96, 4158),  # Jungfrau
    (46.47,  7.99, 4193),  # Aletschhorn
    (46.38,  9.91, 4049),  # Piz Bernina
    (45.52,  7.24, 4061),  # Gran Paradiso
    (46.51, 10.54, 3905),  # Ortler
    (47.07, 12.69, 3798),  # Grossglockner
    (47.42, 10.98, 2962),  # Zugspitze
    (47.07, 11.50, 3440),  # Wildspitze
    (46.50, 13.71, 2864),  # Triglav
    (44.10,  6.73, 3143),  # Mercantour (Maritime Alps)
    # --- Pyrenees ---
    (42.66,  2.90, 2872),  # Canigou
    (42.76,  0.74, 3404),  # Vignemale
    (42.63, -0.66, 3355),  # Posets
    # --- Scandinavia ---
    (61.63,  8.31, 2469),  # Galdhøpiggen
    (62.36,  8.11, 2286),  # Snøhetta
    (69.38, 20.57, 1884),  # Kebnekaise
    # --- Rockies (North America) ---
    (51.16,-115.56, 3619), # Mt Assiniboine
    (52.10,-117.44, 3747), # Mt Columbia
    (46.85,-121.73, 4392), # Mt Rainier
    (63.07,-150.96, 6190), # Denali
    # --- Andes ---
    (-32.65,-70.01, 6962), # Aconcagua
    # --- Himalaya ---
    (27.99,  86.93, 8849), # Everest
    (35.88,  76.51, 8611), # K2
]

# Low-elevation anchors to ensure IDW stays near sea level in plains/oceans
_ANCHORS: list[tuple[float, float, float]] = [
    (52.0,   5.0,   10),   # Netherlands
    (51.5,  -0.1,   30),   # London
    (47.5,   1.5,  120),   # France centre
    (48.2,  11.5,  520),   # Munich / Bavaria
    (47.0,   7.5,  430),   # Swiss Plateau
    (48.0,  16.5,  170),   # Vienna
    (45.5,  12.0,    5),   # Po delta
    (44.5,   8.0,   30),   # Genoa coast
    (55.0,  37.0,  150),   # Moscow
    (40.0, -75.0,   50),   # US East Coast
    (37.0,-122.0,   50),   # California
    (35.0, 139.0,   50),   # Tokyo
    (-34.0, 151.0,  50),   # Sydney
    ( 0.0,   0.0,    0),   # equatorial anchor
    (90.0,   0.0,    0),   # north pole anchor (sea ice ignored)
    (-90.0,  0.0,    0),   # south pole anchor
]

_ALL_POINTS = _PEAKS + _ANCHORS
_PT_LATS = np.array([p[0] for p in _ALL_POINTS], dtype=np.float64)
_PT_LONS = np.array([p[1] for p in _ALL_POINTS], dtype=np.float64)
_PT_ELEVS = np.array([p[2] for p in _ALL_POINTS], dtype=np.float64)

# IDW power (higher = sharper mountain shapes)
_IDW_POWER = 3

# Legacy synthetic parameters kept only for the private _render_synthetic helper.
# Real-data-only flow does not call this path.
_ALPINE_SNOWLINE: dict[int, float] = {
    1: 1200, 2: 1300, 3: 1500, 4: 1800, 5: 2200, 6: 2600,
    7: 3000, 8: 3200, 9: 2800, 10: 2200, 11: 1700, 12: 1400,
}
_CLOUD_PROB: dict[int, float] = {
    1: 0.25, 2: 0.22, 3: 0.20, 4: 0.18, 5: 0.15, 6: 0.12,
    7: 0.10, 8: 0.10, 9: 0.13, 10: 0.20, 11: 0.25, 12: 0.28,
}

# ---------------------------------------------------------------------------
# Tile helpers
# ---------------------------------------------------------------------------

TILE_SIZE = 256
_GRID = 64     # sample grid per axis; upscaled to TILE_SIZE at render time
_BLOCK = 8     # coherence block size in grid cells (creates ~5 km snow patches)


def _tile_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return (lon_min, lat_min, lon_max, lat_max) in WGS-84 for an XYZ tile."""
    n = 1 << z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def _elevation_grid(lat_grid: np.ndarray, lon_grid: np.ndarray) -> np.ndarray:
    """
    Vectorised IDW elevation estimate from the combined peaks+anchors table.
    Returns elevation in metres, same shape as lat_grid / lon_grid.
    """
    # Broadcast: shape (N_points, GRID, GRID)
    dlat = lat_grid[np.newaxis] - _PT_LATS[:, np.newaxis, np.newaxis]
    dlon = (lon_grid[np.newaxis] - _PT_LONS[:, np.newaxis, np.newaxis]) * np.cos(
        np.radians(lat_grid[np.newaxis])
    )
    dist = np.sqrt(dlat ** 2 + dlon ** 2)          # degrees, ~111 km per degree
    dist_p = np.maximum(dist, 0.01) ** _IDW_POWER   # avoid division by zero

    weights = 1.0 / dist_p                           # shape (N_points, GRID, GRID)
    elev = np.sum(weights * _PT_ELEVS[:, np.newaxis, np.newaxis], axis=0) / (
        np.sum(weights, axis=0) + 1e-12
    )
    return np.clip(elev, 0.0, 8850.0)


# ---------------------------------------------------------------------------
# FSC pixel value → RGBA
# ---------------------------------------------------------------------------

def _fsc_rgba_vectorised(
    fsc: np.ndarray,
) -> np.ndarray:
    """
    Map a 2-D integer array of FSC values to an (H, W, 4) uint8 RGBA array.

    Encoding (matches Copernicus HR-WSI convention used in fsc_provider.py):
      0 – 100  fractional snow cover %
      205      cloud-obscured
      255      confirmed snow-free
    """
    h, w = fsc.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    # Cloud: light grey, semi-transparent
    cloud = fsc == 205
    rgba[cloud] = (180, 180, 180, 80)

    # Snow-free: fully transparent (let base map show through)
    # (no-op, array is already zero)

    # Snow (1 – 100): blue → white gradient, alpha ~200
    snow = (fsc >= 1) & (fsc <= 100)
    pct = fsc[snow].astype(np.float32) / 100.0
    rgba[snow, 0] = np.clip(59  + (255 - 59)  * pct, 0, 255).astype(np.uint8)
    rgba[snow, 1] = np.clip(130 + (255 - 130) * pct, 0, 255).astype(np.uint8)
    rgba[snow, 2] = np.clip(246 + (255 - 246) * pct, 0, 255).astype(np.uint8)
    rgba[snow, 3] = np.clip(210 - 70 * pct, 100, 210).astype(np.uint8)

    return rgba


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_fsc_tile(
    z: int,
    x: int,
    y: int,
    tile_date: Optional[date] = None,
) -> bytes:
    """
    Generate a 256 × 256 RGBA PNG tile for the given XYZ coordinate.

    Uses real Copernicus HR-WSI FSC GeoTIFFs (via fsc_tiff.render_tile).
    If no real TIFF covers the requested tile, returns an explicit no-data tile.
    """
    # ── Try real data first ─────────────────────────────────────────────────
    from .fsc_tiff import render_tile as _render_real
    real = _render_real(z, x, y)
    if real is not None:
        return real

    # ── No-data fallback (real-data-only mode) ──────────────────────────────
    return _render_no_data_tile()


def _render_no_data_tile() -> bytes:
    """Render a fully transparent tile to indicate no real FSC data coverage."""
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _render_synthetic(
    z: int,
    x: int,
    y: int,
    tile_date: Optional[date] = None,
) -> bytes:
    """
    Synthetic IDW-elevation-based FSC tile (original implementation).
    Used as fallback when no real GeoTIFF covers the requested tile.
    """
    if tile_date is None:
        tile_date = date.today()

    lon_min, lat_min, lon_max, lat_max = _tile_bbox(z, x, y)

    # ── Coordinate grids ────────────────────────────────────────────────────
    rows = np.arange(_GRID)
    cols = np.arange(_GRID)
    lats_1d = lat_max - (lat_max - lat_min) * (rows + 0.5) / _GRID
    lons_1d = lon_min + (lon_max - lon_min) * (cols + 0.5) / _GRID
    lat_grid, lon_grid = np.meshgrid(lats_1d, lons_1d, indexing="ij")

    # ── Elevation (metres) ──────────────────────────────────────────────────
    elev = _elevation_grid(lat_grid, lon_grid)

    # ── Snow line for this month ────────────────────────────────────────────
    month = tile_date.month
    snowline = _ALPINE_SNOWLINE.get(month, 2200)
    delta = elev - snowline  # positive = above snow line

    # ── Spatially-coherent noise (block-level, reproducible per tile+date) ──
    rng = np.random.default_rng(
        seed=z * 10_000_000 + x * 10_000 + y + tile_date.toordinal()
    )
    n_blocks = _GRID // _BLOCK + 1
    noise_block = rng.integers(-28, 28, size=(n_blocks, n_blocks), dtype=np.int32)
    noise = np.repeat(np.repeat(noise_block, _BLOCK, axis=0), _BLOCK, axis=1)[
        :_GRID, :_GRID
    ]

    # ── Cloud mask ──────────────────────────────────────────────────────────
    cloud_prob = _CLOUD_PROB.get(month, 0.12)
    cloud_block_rng = np.random.default_rng(
        seed=z * 77_777_777 + x * 7_777 + y + tile_date.toordinal()
    )
    cloud_noise = cloud_block_rng.random(size=(n_blocks, n_blocks))
    cloud_upsampled = np.repeat(
        np.repeat(cloud_noise, _BLOCK, axis=0), _BLOCK, axis=1
    )[:_GRID, :_GRID]
    cloud_mask = cloud_upsampled < cloud_prob

    # ── FSC values ──────────────────────────────────────────────────────────
    fsc = np.where(delta < -600, 255, 0).astype(np.int32)

    transition = (delta >= -600) & (delta < 0)
    fsc[transition] = np.clip(
        (delta[transition] + 600) / 6 + noise[transition], 0, 100
    ).astype(np.int32)
    fsc[(transition) & (fsc == 0)] = 255

    above = delta >= 0
    fsc[above] = np.clip(
        40 + delta[above] / 8 + noise[above], 1, 100
    ).astype(np.int32)

    fsc[cloud_mask] = 205

    # ── Render ──────────────────────────────────────────────────────────────
    rgba = _fsc_rgba_vectorised(fsc)
    img = Image.fromarray(rgba, "RGBA").resize(
        (TILE_SIZE, TILE_SIZE), Image.BILINEAR
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()

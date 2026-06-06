"""
SnowRoute API — FastAPI application entry point.

Endpoints
---------
POST /api/v1/analyse        — GeoJSON LineString body
POST /api/v1/analyse/gpx    — multipart GPX file upload
GET  /api/v1/tiles/fsc/{z}/{x}/{y}.png  — FSC raster tiles (XYZ)
GET  /health
"""

import os
from datetime import date as date_type
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .analysis import analyse_route
from .fsc_provider import _USE_REAL, _PROD_TYPE, _CACHE_DIR, _S3_MAX_AGE
from .gpx_parser import parse_gpx
from .models import AnalyseRequest, AnalysisResponse
from .tiles import render_fsc_tile
from .fsc_tiff import coverage_info as _fsc_coverage_info, render_tile_from_cache as _render_real_tile

app = FastAPI(
    title="SnowRoute API",
    version="0.1.0",
    description="Mountain snow conditions analysis service (MVP).",
)

# ── CORS ────────────────────────────────────────────────────────────────────
_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.post("/api/v1/analyse", response_model=AnalysisResponse, tags=["analysis"])
def analyse_geojson(request: AnalyseRequest):
    """
    Analyse snow conditions along a GeoJSON LineString route.

    Coordinates must be in [longitude, latitude] or
    [longitude, latitude, elevation_m] order (standard GeoJSON).
    """
    raw = request.route.coordinates
    if not raw:
        raise HTTPException(status_code=400, detail="Route has no coordinates.")

    # GeoJSON [lon, lat, ?elev] → internal (lat, lon, ?elev)
    coords = [
        (c[1], c[0], c[2] if len(c) >= 3 else None)
        for c in raw
    ]

    opts = request.options
    steep = opts.steep_threshold_deg if opts else 30.0
    max_age = opts.max_data_age_days if opts else 7

    try:
        return analyse_route(coords, steep_threshold_deg=steep, max_data_age_days=max_age)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/analyse/gpx", response_model=AnalysisResponse, tags=["analysis"])
async def analyse_gpx(
    file: UploadFile = File(..., description="GPX file (tracks, routes, or waypoints)"),
    steep_threshold_deg: float = Query(default=30.0, ge=0, le=90),
    max_data_age_days: int = Query(default=7, ge=1, le=30),
):
    """
    Analyse snow conditions along a route from an uploaded GPX file.
    """
    if file.content_type not in (
        "application/gpx+xml",
        "application/xml",
        "text/xml",
        "application/octet-stream",
    ) and not (file.filename or "").lower().endswith(".gpx"):
        raise HTTPException(
            status_code=415,
            detail="Expected a GPX file (.gpx).",
        )

    content = await file.read()
    try:
        coords = parse_gpx(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not coords:
        raise HTTPException(
            status_code=400, detail="No route points found in GPX file."
        )

    try:
        return analyse_route(
            coords,
            steep_threshold_deg=steep_threshold_deg,
            max_data_age_days=max_data_age_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── FSC tile endpoint (DesignDoc §12.2) ──────────────────────────────────────

@app.get(
    "/api/v1/tiles/fsc/{z}/{x}/{y}.png",
    tags=["tiles"],
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def fsc_tile(
    z: int,
    x: int,
    y: int,
    date: Optional[str] = Query(
        default=None,
        description="ISO date YYYY-MM-DD for the FSC mosaic. Defaults to today.",
    ),
):
    """
    Serve a 256 × 256 RGBA PNG tile showing Fractional Snow Cover (FSCOG)
    for the requested XYZ tile coordinate and date.

    Colour scheme:
      - Blue → white gradient  (FSC 1 – 100 %, low → high coverage)
      - Light grey             (cloud-obscured, FSC 205)
      - Transparent            (snow-free, FSC 255)

    This endpoint is intentionally designed as a drop-in replacement:
    swap render_fsc_tile() with a PostGIS/TiTiler query against the real
    CLMS HR-WSI FSCOG mosaic table once the data pipeline is running.
    """
    tile_date = date_type.today()
    if date:
        try:
            tile_date = date_type.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid date '{date}': use YYYY-MM-DD."
            ) from exc

    if z < 0 or z > 22 or x < 0 or x >= (1 << z) or y < 0 or y >= (1 << z):
        raise HTTPException(status_code=400, detail="Tile coordinates out of range.")

    if _USE_REAL:
        png = _render_real_tile(
            z, x, y, _CACHE_DIR, tile_date.isoformat(), _PROD_TYPE, _S3_MAX_AGE
        )
    else:
        png = render_fsc_tile(z, x, y, tile_date)

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-FSC-Date": tile_date.isoformat(),
        },
    )


# ── FSC dataset info ──────────────────────────────────────────────────────────

@app.get("/api/v1/fsc/info", tags=["tiles"])
def fsc_info():
    """
    Return metadata about the FSC datasets available on this server.

    When real Copernicus GeoTIFF files are loaded (FSC_DATA_DIR or the default
    sibling snow-coverage directory), the response includes the acquisition date
    and the WGS-84 bounding box of all indexed tiles — useful for the frontend
    to auto-zoom and show a "real data" badge.
    """
    return _fsc_coverage_info()


@app.get("/api/v1/fsc/status", tags=["tiles"])
def fsc_status(
    lat: float = Query(default=47.5, description="Test latitude (WGS-84)"),
    lon: float = Query(default=12.0, description="Test longitude (WGS-84)"),
):
    """
    Diagnostic endpoint: shows active FSC data mode and probes S3 availability.

    Performs a live S3 query for the supplied test coordinate so you can
    verify real-data connectivity without uploading a GPX file.
    """
    from datetime import date as _date
    status: dict = {
        "mode": "real_data" if _USE_REAL else "mock",
        "FSC_USE_REAL_DATA": _USE_REAL,
        "FSC_PRODUCT_TYPE": _PROD_TYPE,
        "FSC_CACHE_DIR": _CACHE_DIR,
        "FSC_S3_MAX_AGE_DAYS": _S3_MAX_AGE,
        "s3_probe": None,
    }

    if _USE_REAL:
        from . import fsc_s3
        tile = fsc_s3.get_mgrs_tile(lat, lon)
        today = _date.today().isoformat()
        try:
            result = fsc_s3.find_product_key(tile, today, _PROD_TYPE, _S3_MAX_AGE)
            status["s3_probe"] = {
                "tile": tile,
                "query_date": today,
                "found": result is not None,
                "s3_key": result[0] if result else None,
                "actual_date": result[1] if result else None,
            }
        except Exception as exc:
            status["s3_probe"] = {"tile": tile, "error": str(exc)}

    return status


@app.get("/api/v1/fsc/available-dates", tags=["tiles"])
def fsc_available_dates(
    lat: float = Query(..., description="Latitude (WGS-84) of any route point"),
    lon: float = Query(..., description="Longitude (WGS-84) of any route point"),
    year: int = Query(..., ge=2000, le=2100, description="Calendar year"),
    month: int = Query(..., ge=1, le=12, description="Calendar month (1–12)"),
):
    """
    List all days in a month for which Copernicus GFSC data exists in S3
    for the MGRS tile covering the given coordinate.

    Returns an empty list when the server is running in mock mode
    (FSC_USE_REAL_DATA=false).
    """
    if not _USE_REAL:
        return {"dates": [], "tile": None, "mode": "mock"}

    from . import fsc_s3

    tile = fsc_s3.get_mgrs_tile(lat, lon)
    dates = fsc_s3.list_available_dates_for_month(tile, year, month, _PROD_TYPE)
    return {"dates": dates, "tile": tile}

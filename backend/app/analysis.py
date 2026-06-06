"""
Route analysis engine — implements the algorithm from DesignDoc §9.2.

Classify each route point, aggregate statistics, and derive the
overall safety indicator (GREEN / AMBER / RED).
"""

from datetime import date
from typing import List, Optional, Tuple

from .fsc_provider import compute_slope, get_fsc_value
from .fsc_provider import _USE_REAL
from .copernicus_trace import CopernicusTraceCollector
from . import fsc_s3
from .models import AnalysisResponse, SegmentResult, Summary

# Maximum points sampled from a route to bound query latency
_MAX_POINTS = 500

# ── Classification ──────────────────────────────────────────────────────────

_RISK_CLEAR = "clear"
_RISK_LOW = "snow_low_risk"
_RISK_HIGH = "snow_high_risk"
_RISK_CLOUD = "cloud_obscured"
_RISK_WATER = "water"


def _classify(fsc: int, slope_deg: float, steep_threshold: float) -> str:
    if fsc == 205:
        return _RISK_CLOUD
    if fsc == 210:
        return _RISK_WATER
    if fsc == 255 or fsc == 0:
        return _RISK_CLEAR
    return _RISK_HIGH if slope_deg >= steep_threshold else _RISK_LOW


def _safety_indicator(
    snow_pct: float, high_risk_pct: float, cloud_pct: float
) -> str:
    """
    GREEN  : < 5 % snow  OR  all snow low-risk and total < 20 %
    AMBER  : 5–30 % snow  OR  any high-risk snow present
    RED    : > 30 % snow  OR  > 10 % high-risk snow  OR  > 40 % cloud gap
    """
    if cloud_pct > 40 or high_risk_pct > 10 or snow_pct > 30:
        return "RED"
    if snow_pct >= 5 or high_risk_pct > 0:
        return "AMBER"
    return "GREEN"


# ── Public API ───────────────────────────────────────────────────────────────

def analyse_route(
    coords: List[Tuple[float, float, Optional[float]]],
    steep_threshold_deg: float = 30.0,
    max_data_age_days: int = 7,
    analysis_date: Optional[date] = None,
) -> AnalysisResponse:
    """
    Analyse snow conditions along the supplied list of (lat, lon, elev?) tuples.

    Large GPX tracks are sub-sampled to _MAX_POINTS to bound latency while
    preserving route shape.
    """
    if not coords:
        raise ValueError("Route contains no points.")

    # Sub-sample evenly if track is very dense
    if len(coords) > _MAX_POINTS:
        step = len(coords) // _MAX_POINTS
        coords = coords[::step]

    if analysis_date is None:
        analysis_date = date.today()

    segments: List[SegmentResult] = []
    trace = CopernicusTraceCollector(mode="real_data" if _USE_REAL else "mock")
    trace_token = fsc_s3.set_trace_collector(trace)

    try:
        for i, (lat, lon, elev) in enumerate(coords):
            fsc, acq_date = get_fsc_value(lat, lon, elev, analysis_date)

            # Slope: use segment to the next point; fall back to previous
            if i + 1 < len(coords):
                n_lat, n_lon, n_elev = coords[i + 1]
                slope = compute_slope(lat, lon, elev, n_lat, n_lon, n_elev)
            elif i > 0:
                p_lat, p_lon, p_elev = coords[i - 1]
                slope = compute_slope(p_lat, p_lon, p_elev, lat, lon, elev)
            else:
                slope = 0.0

            # Treat data older than the configured window as cloud-obscured
            data_age = (analysis_date - acq_date).days
            if data_age > max_data_age_days:
                fsc = 205
                risk_class = _RISK_CLOUD
            else:
                risk_class = _classify(fsc, slope, steep_threshold_deg)

            segments.append(
                SegmentResult(
                    index=i,
                    lat=lat,
                    lon=lon,
                    fsc_pct=fsc if 0 <= fsc <= 100 else None,
                    slope_deg=round(slope, 1),
                    risk_class=risk_class,
                    acquisition_date=acq_date.isoformat(),
                )
            )
    finally:
        fsc_s3.reset_trace_collector(trace_token)

    # ── Aggregation ────────────────────────────────────────────────────────
    n = len(segments)
    low_n = sum(1 for s in segments if s.risk_class == _RISK_LOW)
    high_n = sum(1 for s in segments if s.risk_class == _RISK_HIGH)
    cloud_n = sum(1 for s in segments if s.risk_class == _RISK_CLOUD)

    snow_pct = round((low_n + high_n) / n * 100, 1)
    high_risk_pct = round(high_n / n * 100, 1)
    cloud_pct = round(cloud_n / n * 100, 1)

    ages = [
        (analysis_date - date.fromisoformat(s.acquisition_date)).days
        for s in segments
        if s.risk_class != _RISK_CLOUD
    ]
    if ages:
        age_min, age_max = min(ages), max(ages)
        age_mean = round(sum(ages) / len(ages), 1)
    else:
        age_min = age_max = max_data_age_days
        age_mean = float(max_data_age_days)

    summary = Summary(
        safety_indicator=_safety_indicator(snow_pct, high_risk_pct, cloud_pct),
        snow_covered_pct=snow_pct,
        high_risk_snow_pct=high_risk_pct,
        cloud_obscured_pct=cloud_pct,
        data_age_days={"min": age_min, "max": age_max, "mean": age_mean},
    )

    return AnalysisResponse(
        summary=summary,
        segments=segments,
        copernicus_trace=trace.to_model(),
    )

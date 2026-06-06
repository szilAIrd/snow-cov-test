"""
GPX file parser — extracts track/route/waypoint coordinates.
Returns list of (lat, lon, elevation_m | None) tuples.
"""

import gpxpy
from typing import List, Optional, Tuple


def parse_gpx(content: bytes) -> List[Tuple[float, float, Optional[float]]]:
    try:
        gpx = gpxpy.parse(content.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot parse GPX: {exc}") from exc

    points: List[Tuple[float, float, Optional[float]]] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append((pt.latitude, pt.longitude, pt.elevation))

    if not points:
        for route in gpx.routes:
            for pt in route.points:
                points.append((pt.latitude, pt.longitude, pt.elevation))

    if not points:
        for wp in gpx.waypoints:
            points.append((wp.latitude, wp.longitude, wp.elevation))

    return points

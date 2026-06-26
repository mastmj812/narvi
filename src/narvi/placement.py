"""Geometry core: drillable window + parallel leg placement.

All geometry is in the work CRS (UTM 13N, metres). Azimuth is the compass bearing
(cw from N) the laterals run along.

Method: rotate the window so the azimuth aligns with +x, lay parallel rows
`spacing` apart in y, clip each to the (possibly non-convex) window, keep the rows
meeting the minimum length. Leg placement returns the rows IN THE ROTATED FRAME
(heels at low x, toes at high x) so the generator can build U-turn arcs trivially,
then map points back with unrotate().
"""

from __future__ import annotations

import math

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from .records import FT_PER_M


def dominant_azimuth(parcel: BaseGeometry) -> float:
    """Compass bearing (deg, 0-180) of the parcel's long axis, from its minimum
    rotated rectangle. A dependency-free stand-in for the RRC survey-section grid
    until the survey shapefiles are wired (Phase 4): for a section-shaped parcel
    the long edge tracks the grid, so laterals laid along it stay full-length
    instead of getting clipped by a tilted boundary."""
    rect = parcel.minimum_rotated_rectangle
    pts = list(rect.exterior.coords)[:4]
    edges = [(pts[i], pts[i + 1]) for i in range(3)]
    (x0, y0), (x1, y1) = max(edges, key=lambda e: math.dist(e[0], e[1]))
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180.0


def drillable_window(parcel: BaseGeometry, setback_ft: float) -> BaseGeometry:
    """Inward offset by a uniform setback (slice 1; asymmetric edge-strip later)."""
    return parcel.buffer(-setback_ft / FT_PER_M, join_style=2)


def _longest_segment(geom: BaseGeometry) -> LineString | None:
    if geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        return max(geom.geoms, key=lambda g: g.length)
    return None


def laterals_rotated(
    window: BaseGeometry,
    azimuth_deg: float,
    spacing_ft: float,
    min_lateral_ft: float,
) -> tuple[list[tuple[float, float, float]], Point, float, float]:
    """Place parallel rows along `azimuth_deg`. Returns (legs, centroid, phi, y_mid)
    where legs = [(y, x_heel, x_toe), ...] in the rotated frame (azimuth -> +x),
    sorted by y. Map a rotated point back to the work CRS with unrotate()."""
    if window.is_empty:
        return [], window.centroid, 0.0, 0.0

    centroid = window.centroid
    phi = 90.0 - azimuth_deg                 # compass bearing -> math angle
    rot = rotate(window, -phi, origin=centroid, use_radians=False)  # laterals -> +x
    minx, miny, maxx, maxy = rot.bounds
    spacing_m = spacing_ft / FT_PER_M
    min_m = min_lateral_ft / FT_PER_M
    y_mid = (miny + maxy) / 2.0

    n_each = int(((maxy - miny) / 2.0) // spacing_m)
    legs: list[tuple[float, float, float]] = []
    for k in range(-n_each, n_each + 1):
        y = y_mid + k * spacing_m
        seg = _longest_segment(LineString([(minx - 10.0, y), (maxx + 10.0, y)]).intersection(rot))
        if seg is None or seg.length < min_m:
            continue
        xs = [c[0] for c in seg.coords]
        legs.append((y, min(xs), max(xs)))  # heel = low x (west), toe = high x (east)

    legs.sort(key=lambda t: t[0])
    return legs, centroid, phi, y_mid


def unrotate(x: float, y: float, centroid: Point, phi: float) -> tuple[float, float]:
    """Map a rotated-frame point back to the work CRS."""
    p = rotate(Point(x, y), phi, origin=centroid, use_radians=False)
    return (p.x, p.y)

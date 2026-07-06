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
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

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


def anchor_edge_azimuth(parcel: BaseGeometry, anchor: str) -> float | None:
    """Bearing (deg, 0-180) of the lease line the development hangs off — 'west' or
    'east'. The user stipulates the line by choosing the anchor; that line DEFINES
    the azimuth, because laterals are developed parallel to the setback. Deriving the
    azimuth from the line (instead of a warehouse grid or the bbox long axis) keeps
    the laterals exactly parallel to the 330 ft setback — no fractional-degree drift,
    and the anchor edge falls axis-aligned in the work frame so its setback row sits
    flush on the line. The anchor edge = the longest exterior edge whose outward
    normal points most in the chosen direction (west = -Easting, east = +Easting)."""
    want = -1.0 if anchor == "west" else 1.0
    polys = list(parcel.geoms) if isinstance(parcel, MultiPolygon) else [parcel]
    best_score, best_az = 0.0, None
    for poly in polys:
        poly = orient(poly, 1.0)  # exterior CCW -> outward normal is (dy, -dx)
        cs = list(poly.exterior.coords)
        for (ax, ay), (bx, by) in zip(cs, cs[1:]):
            dx, dy = bx - ax, by - ay
            seg_len = math.hypot(dx, dy)
            if seg_len == 0.0:
                continue
            nx = dy / seg_len                       # outward-normal Easting component
            score = seg_len * (want * nx)           # west/east-facing, length-weighted
            if score > best_score:
                best_score = score
                best_az = math.degrees(math.atan2(dx, dy)) % 180.0
    return best_az


def drillable_window(
    parcel: BaseGeometry, setback_ns_ft: float, setback_ew_ft: float | None = None
) -> BaseGeometry:
    """Inward setback. Uniform (one value, or N/S == E/W) uses a robust negative
    buffer; asymmetric (N/S vs E/W differ) uses per-edge strip subtraction."""
    ew = setback_ns_ft if setback_ew_ft is None else setback_ew_ft
    if abs(setback_ns_ft - ew) < 1e-6:
        return parcel.buffer(-setback_ns_ft / FT_PER_M, join_style=2)
    return _edge_strip_window(parcel, setback_ns_ft, ew)


def _edge_strip_window(parcel: BaseGeometry, setback_ns_ft: float, setback_ew_ft: float) -> BaseGeometry:
    """Per-edge inward strips: classify each boundary edge as N/S- or E/W-facing by
    its outward normal and subtract a strip of the matching setback. Local strips
    (not infinite half-planes), so it's robust to non-convex parcels / notches."""
    ns = setback_ns_ft / FT_PER_M
    ew = setback_ew_ft / FT_PER_M
    polys = list(parcel.geoms) if isinstance(parcel, MultiPolygon) else [parcel]
    strips = []
    for poly in polys:
        poly = orient(poly, 1.0)  # exterior CCW, holes CW -> interior is LEFT of each edge
        for ring in [poly.exterior, *poly.interiors]:
            cs = list(ring.coords)
            for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                dx, dy = bx - ax, by - ay
                if dx == 0 and dy == 0:
                    continue
                # outward normal = (dy, -dx); N/S-facing when |dx| >= |dy|
                d = ns if abs(dx) >= abs(dy) else ew
                if d > 0:  # single_sided buffers left of the line = inward (CCW ring)
                    strips.append(LineString([(ax, ay), (bx, by)]).buffer(d, single_sided=True))
    if not strips:
        return parcel
    return parcel.difference(unary_union(strips))


def _longest_segment(geom: BaseGeometry) -> LineString | None:
    if geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        return max(geom.geoms, key=lambda g: g.length)
    return None


def _flush_anchor_y(rot, minx, maxx, miny, maxy, edge_y, into, spacing_m, min_m) -> float:
    """March inward from a W/E window edge to the first row flush against the FULL
    boundary. When the edge runs ~parallel to the laterals, a constant-cross-section
    row at the extreme corner grazes a single point (length ~0), so anchoring there
    leaves the first real lateral a whole spacing inside the setback line. Step in
    until the lateral reaches ~90% of the length one spacing further in (the start of
    the full plateau) and anchor there, so the first leg sits ON the setback line."""
    def length_at(y: float) -> float:
        if not (miny - 1.0 <= y <= maxy + 1.0):
            return 0.0
        seg = _longest_segment(LineString([(minx - 10.0, y), (maxx + 10.0, y)]).intersection(rot))
        return seg.length if seg is not None else 0.0

    def on_plateau(y: float) -> bool:
        L = length_at(y)
        return L >= min_m and L >= 0.9 * length_at(y + into * spacing_m)

    step = into * spacing_m / 40.0
    for i in range(40):                       # coarse scan for the first full row
        y = edge_y + i * step
        if on_plateau(y):
            # bisect the bracket [last-not-full, first-full] to land flush ON the
            # setback line (sub-foot), not on the coarse scan step inside it
            lo, hi = edge_y + (i - 1) * step, y
            for _ in range(24):
                mid = (lo + hi) / 2.0
                if on_plateau(mid):
                    hi = mid
                else:
                    lo = mid
            return hi
    return edge_y                             # nothing qualifies -> fall back to the edge


def laterals_rotated(
    window: BaseGeometry,
    azimuth_deg: float,
    spacing_ft: float,
    min_lateral_ft: float,
    row_offset_ft: float = 0.0,
    anchor: str = "center",
) -> tuple[list[tuple[float, float, float]], Point, float, float]:
    """Place parallel rows along `azimuth_deg`. Returns (legs, centroid, phi, y_mid)
    where legs = [(y, x_heel, x_toe), ...] in the rotated frame (azimuth -> +x),
    sorted by y. `row_offset_ft` phase-shifts the rows (the wine-rack stagger across
    zones). `anchor` sets where the row pattern HANGS — 'center' (rows symmetric
    about the unit), 'west' / 'east' (first lateral at that section-line setback,
    stepping across) — which is how development is actually laid out and which row
    falls in an irregular cutout. Map a rotated point back with unrotate()."""
    if window.is_empty:
        return [], window.centroid, 0.0, 0.0

    centroid = window.centroid
    phi = 90.0 - azimuth_deg                 # compass bearing -> math angle
    rot = rotate(window, -phi, origin=centroid, use_radians=False)  # laterals -> +x
    minx, miny, maxx, maxy = rot.bounds
    spacing_m = spacing_ft / FT_PER_M
    min_m = min_lateral_ft / FT_PER_M
    y_mid = (miny + maxy) / 2.0

    if anchor == "center":
        anchor_y = y_mid
    else:
        # rotated +y is one cross-section direction; find which y-edge is WEST
        # (smaller Easting in the work CRS) so 'west'/'east' map correctly.
        xmid = (minx + maxx) / 2.0
        e_lo = rotate(Point(xmid, miny), phi, origin=centroid, use_radians=False).x
        e_hi = rotate(Point(xmid, maxy), phi, origin=centroid, use_radians=False).x
        west_y, east_y = (miny, maxy) if e_lo <= e_hi else (maxy, miny)
        edge_y = west_y if anchor == "west" else east_y
        # anchor the first lateral flush ON the setback line (the window's W/E edge),
        # stepping past a degenerate corner graze when that edge ~parallels the grid.
        into = 1.0 if edge_y == miny else -1.0
        anchor_y = _flush_anchor_y(rot, minx, maxx, miny, maxy, edge_y, into, spacing_m, min_m)

    # rows at anchor + offset + k*spacing, k chosen to span the whole window
    base = anchor_y + row_offset_ft / FT_PER_M
    k_lo = math.ceil((miny - base) / spacing_m)
    k_hi = math.floor((maxy - base) / spacing_m)
    legs: list[tuple[float, float, float]] = []
    for k in range(k_lo, k_hi + 1):
        y = base + k * spacing_m
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


def cross_axis(azimuth_deg: float) -> tuple[float, float]:
    """THE canonical gun-barrel cross-section axis (unit vector, work-CRS E/N).
    The azimuth is folded to [0,180) (axial — a lateral has no direction); the
    axis is 90° clockwise of it, so +offset = the right-hand side looking down
    the folded azimuth: compass EAST for N-S laterals, compass SOUTH for E-W.
    Every gunbarrel_x_ft in narvi (generated wells AND warehouse pass-throughs)
    projects onto this axis so the two populations overlay correctly."""
    a = math.radians(azimuth_deg % 180.0)
    return (math.cos(a), -math.sin(a))


def gunbarrel_offset_ft(
    xy: tuple[float, float], azimuth_deg: float, origin_xy: tuple[float, float]
) -> float:
    """Signed cross-section offset (ft) of a work-CRS point from `origin_xy`
    along cross_axis(azimuth_deg). The origin is the PARCEL centroid — a fixed
    landmark shared by generated and warehouse wells, so overlays align."""
    px, py = cross_axis(azimuth_deg)
    return ((xy[0] - origin_xy[0]) * px + (xy[1] - origin_xy[1]) * py) * FT_PER_M

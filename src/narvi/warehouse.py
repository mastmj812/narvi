"""Narvi warehouse data layer (Phase 4, §7) — sources real numbers from the
oilgas warehouse to feed the pure-geometry core.

This module is the ONLY part of narvi that talks to PostgreSQL. The geometry
core (parcel / placement / generate) stays DB-free and unit-testable; this layer
turns hand-typed scenario inputs into data-driven ones:

  * landing TVD per `formation_blueox` from offset wells in the AOI (median +
    spread + a multimodality flag that warns when one bench code is hiding two
    distinct landing targets),
  * a ready-to-use `Zone` list for `generate_wine_rack`, and
  * the section-grid azimuth, derived from the actual lateral bearings of nearby
    horizontal wells (the ground truth for how operators align to the survey
    grid) — more robust than the parcel's own long axis on irregular DSUs.

Connection mirrors engineering_db/etl/db.py: env-var credentials from a
gitignored `.env`, with Supabase session settings (statement_timeout=0,
search_path including `extensions` so PostGIS resolves).

Landing TVD = `curated.wells_enriched.tvd_ft`; the bench code is the
TVD-corrected `formation_blueox` (see [[formation-blueox-crosswalk]]). Geometry
filtering uses `wellstick_geom` (SRID 4326) against the AOI as a geography so the
buffer is a true metric distance.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import psycopg
from dotenv import load_dotenv
from pyproj import CRS, Transformer
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from .parcel import WORK_EPSG
from .placement import cross_axis, gunbarrel_offset_ft
from .records import FT_PER_M, InventoryWell, Leg, Zone

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Two distinct landing targets sharing one formation_blueox code is the thing
# the multimodality flag exists to catch. A real bench-to-bench gap is a few
# hundred feet (e.g. WCA_1 vs WCA_2 ~200 ft); 300 ft between two well-populated
# clusters is a confident "this code spans two targets, split the wine-rack".
_BIMODAL_GAP_FT = 300.0
_BIMODAL_MIN_FRAC = 0.20   # each cluster must hold >= 20% of the wells

# Permit-depth de-weighting (mirrors curated.formation_blueox_tvd, sql/23): a TVD
# that is an exact multiple of 100 ft (12,000 / 11,500 / 10,600 ...) is almost
# always a permit/plan depth carried forward, not a measured landing. Such round
# depths skew the median and — clustered at a round number like 13,000 — fake a
# second mode. We drop them from the stats AS LONG AS enough real-depth wells
# remain; below that floor the bench is too permit-contaminated to filter, so we
# fall back to all wells and flag it instead of silently trusting round numbers.
_PERMIT_MIN_REAL = 3       # keep real-depth stats only if >= this many remain

# Section-grid azimuth from offset laterals. Wells in a development block are
# drilled parallel to the survey grid, so their lateral bearings are a tight,
# coherent population — UNLESS the AOI straddles two survey blocks with different
# grid rotations, in which case the bearings scatter. Coherence R (mean resultant
# length, 0..1) measures that tightness; below the floor we don't trust a single
# grid azimuth and fall back to the parcel's own long axis.
_AZIMUTH_MIN_COHERENCE = 0.85
_AZIMUTH_MIN_WELLS = 3
_AZIMUTH_MIN_LATERAL_M = 500.0   # ignore near-coincident LP/BHL (vertical/sidetrack noise)


_SESSION_SETTINGS: tuple[str, ...] = (
    "SET statement_timeout = 0",
    "SET search_path TO public, extensions",
)

# parcel work CRS (UTM 13N, metres) -> WGS84 lon/lat for the spatial filter
_to_wgs = Transformer.from_crs(
    CRS.from_epsg(WORK_EPSG), CRS.from_epsg(4326), always_xy=True
).transform
# WGS84 lon/lat -> work CRS, for building leg geometry from warehouse points
_to_work = Transformer.from_crs(
    CRS.from_epsg(4326), CRS.from_epsg(WORK_EPSG), always_xy=True
).transform


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def _db_kwargs() -> dict[str, str]:
    return {
        "host": _required_env("DB_HOST"),
        "port": os.getenv("DB_PORT", "6543"),
        "dbname": _required_env("DB_NAME"),
        "user": _required_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "sslmode": os.getenv("DB_SSLMODE", "prefer"),
        "connect_timeout": os.getenv("DB_CONNECT_TIMEOUT", "30"),
        # Apply session GUCs as startup options rather than a per-session SET: on the
        # transaction pooler (6543) a mid-session `SET` doesn't persist across the
        # multiplexed server connection, so statement_timeout/search_path must ride
        # the startup packet. Harmless on session mode too.
        "options": "-c statement_timeout=0 -c search_path=public,extensions",
        "keepalives": "1",
        "keepalives_idle": "30",
        "keepalives_interval": "10",
        "keepalives_count": "5",
    }


def db_conninfo() -> str:
    """psycopg conninfo string for building a ConnectionPool (backend/app/db.py)."""
    return psycopg.conninfo.make_conninfo(**_db_kwargs())


def apply_session_settings(conn: psycopg.Connection) -> None:
    """Supabase-friendly session settings; pool `configure` hook + get_connection."""
    with conn.cursor() as cur:
        for stmt in _SESSION_SETTINGS:
            cur.execute(stmt)
    conn.commit()


def get_connection() -> psycopg.Connection:
    """Open a psycopg (v3) connection with Supabase-friendly session settings."""
    conn = psycopg.connect(**_db_kwargs())
    apply_session_settings(conn)
    return conn


def parcel_to_ewkt_4326(parcel: BaseGeometry) -> str:
    """Project a work-CRS (UTM 13N) parcel to a WGS84 EWKT string for the AOI
    filter. `ST_GeogFromText` accepts the `SRID=4326;...` prefix."""
    wgs = shp_transform(lambda x, y, z=None: _to_wgs(x, y), parcel)
    return f"SRID=4326;{wgs.wkt}"


@dataclass
class LandingTvdStats:
    """Landing-TVD summary for one formation_blueox in an AOI (+ buffer)."""

    formation: str
    wells: int                      # total horizontal wells found in the AOI
    wells_used: int                 # wells the stats are computed on (real-depth)
    permit_round_dropped: int       # round-100 (permit) depths excluded from stats
    permit_contaminated: bool       # too few real depths to filter -> stats use all
    median_tvd_ft: float | None
    p10_tvd_ft: float | None        # shallow tail (10th pct)
    p90_tvd_ft: float | None        # deep tail (90th pct)
    spread_ft: float | None         # p90 - p10
    multimodal: bool                # one code, two distinct landing targets?
    modes_ft: list[float]           # cluster medians when multimodal (else [median])
    note: str = ""


def _split_bimodal(vals: list[float]) -> tuple[bool, list[float]]:
    """Detect a two-target landing-TVD population via the largest interior gap.

    Sort the TVDs; the widest gap between consecutive values is the natural
    split. If that gap clears `_BIMODAL_GAP_FT` AND both sides hold at least
    `_BIMODAL_MIN_FRAC` of the wells, call it bimodal and return each cluster's
    median. This is deliberately conservative — it fires only on a clean,
    well-populated separation, not on a long unimodal tail."""
    n = len(vals)
    if n < 6:  # too few wells to trust a split
        return False, ([_median(vals)] if vals else [])

    s = sorted(vals)
    best_gap, best_i = -1.0, -1
    for i in range(n - 1):
        gap = s[i + 1] - s[i]
        if gap > best_gap:
            best_gap, best_i = gap, i

    lo, hi = s[: best_i + 1], s[best_i + 1:]
    enough = min(len(lo), len(hi)) >= max(2, round(_BIMODAL_MIN_FRAC * n))
    if best_gap >= _BIMODAL_GAP_FT and enough:
        return True, [_median(lo), _median(hi)]
    return False, [_median(s)]


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _percentile(vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]); matches numpy's default."""
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * frac


def landing_tvd_stats(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    formation: str,
    buffer_ft: float = 5280.0,
) -> LandingTvdStats:
    """Median landing TVD for one `formation_blueox` from horizontal offset
    wells whose lateral stick lies within `buffer_ft` of the AOI.

    The parcel is a work-CRS (UTM 13N) geometry from the geometry core; it's
    projected to 4326 here. Default buffer is one mile — wide enough to catch
    section-offset control, tight enough to stay on-structure."""
    aoi = parcel_to_ewkt_4326(parcel)
    buffer_m = buffer_ft / FT_PER_M
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.tvd_ft::float
            FROM curated.wells_enriched w
            WHERE w.is_horizontal
              AND w.formation_blueox = %(formation)s
              AND w.tvd_ft IS NOT NULL
              AND w.tvd_ft > 0
              AND w.wellstick_geom IS NOT NULL
              AND ST_DWithin(
                    w.wellstick_geom::geography,
                    ST_GeogFromText(%(aoi)s),
                    %(buffer_m)s)
            """,
            {"formation": formation, "aoi": aoi, "buffer_m": buffer_m},
        )
        vals = [row[0] for row in cur.fetchall()]

    if not vals:
        return LandingTvdStats(
            formation=formation, wells=0, wells_used=0, permit_round_dropped=0,
            permit_contaminated=False, median_tvd_ft=None,
            p10_tvd_ft=None, p90_tvd_ft=None, spread_ft=None,
            multimodal=False, modes_ft=[],
            note=f"no horizontal {formation} wells within {buffer_ft:.0f} ft of the AOI",
        )

    # Drop permit-round (x100) depths from the stats when enough real depths remain;
    # otherwise the bench is too permit-contaminated to filter -> use all + flag it.
    real = [v for v in vals if v % 100 != 0]
    n_permit = len(vals) - len(real)
    if len(real) >= _PERMIT_MIN_REAL:
        stat_vals, contaminated, dropped = real, False, n_permit
    else:
        stat_vals, contaminated, dropped = vals, n_permit > 0, 0

    med = _median(stat_vals)
    p10 = _percentile(stat_vals, 0.10)
    p90 = _percentile(stat_vals, 0.90)
    multimodal, modes = _split_bimodal(stat_vals)
    note = (f"{len(stat_vals)} {formation} wells; median {med:,.0f} ft "
            f"(P10 {p10:,.0f} / P90 {p90:,.0f}, spread {p90 - p10:,.0f} ft)")
    if dropped:
        note += f"  [dropped {dropped} permit-round depth{'s' if dropped != 1 else ''}]"
    if contaminated:
        note += (f"  [PERMIT-CONTAMINATED: {n_permit}/{len(vals)} round-100 depths, only "
                 f"{len(real)} real -> median is low-confidence]")
    if multimodal:
        note += (f"  [BIMODAL: 2 landing targets ~{modes[0]:,.0f} & {modes[1]:,.0f} ft — "
                 f"consider splitting this bench in the wine-rack]")
    return LandingTvdStats(
        formation=formation, wells=len(vals), wells_used=len(stat_vals),
        permit_round_dropped=dropped, permit_contaminated=contaminated,
        median_tvd_ft=round(med, 1),
        p10_tvd_ft=round(p10, 1), p90_tvd_ft=round(p90, 1),
        spread_ft=round(p90 - p10, 1),
        multimodal=multimodal, modes_ft=[round(m, 1) for m in modes], note=note,
    )


def zones_from_warehouse(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    formations: list[str],
    buffer_ft: float = 5280.0,
    split_multimodal: bool = False,
    min_wells: int = 3,
) -> tuple[list[Zone], list[LandingTvdStats]]:
    """Build a `Zone` list (formation + sourced median landing TVD) for
    `generate_wine_rack`, one per requested `formation_blueox`. Benches with
    fewer than `min_wells` offset wells (too little control to trust the TVD) or
    no control at all are dropped — and surfaced in the returned stats so the gap
    is visible rather than silent.

    When `split_multimodal` is True, a bench flagged as bimodal is emitted as
    two zones (`CODE`, `CODE_b`) at each cluster's median TVD — so a single code
    masking two real targets still racks two benches."""
    zones: list[Zone] = []
    stats: list[LandingTvdStats] = []
    for f in formations:
        st = landing_tvd_stats(conn, parcel, f, buffer_ft)
        # gate on real-depth control (wells_used), not the raw count, so a bench
        # propped up by permit-round depths doesn't sneak past the guard
        if st.median_tvd_ft is not None and st.wells_used < min_wells:
            st.note += f"  [thin control: {st.wells_used} < {min_wells} real-depth wells -> bench dropped]"
        stats.append(st)
        if st.median_tvd_ft is None or st.wells_used < min_wells:
            continue
        if split_multimodal and st.multimodal and len(st.modes_ft) == 2:
            zones.append(Zone(formation=f, target_tvd_ft=st.modes_ft[0]))
            zones.append(Zone(formation=f"{f}_b", target_tvd_ft=st.modes_ft[1]))
        else:
            zones.append(Zone(formation=f, target_tvd_ft=st.median_tvd_ft))
    zones.sort(key=lambda z: z.target_tvd_ft)
    return zones, stats


@dataclass
class AzimuthStats:
    """Section-grid azimuth from offset laterals in an AOI (+ buffer)."""

    wells: int
    azimuth_deg: float | None   # axial bearing folded to [0, 180); None if no control
    coherence: float            # mean resultant length R in [0,1] (grid tightness)
    circ_std_deg: float | None  # circular std of the (axial) bearings, degrees
    confident: bool             # coherence >= floor AND enough wells
    note: str = ""


def lateral_azimuth_stats(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    buffer_ft: float = 5280.0,
    formation: str | None = None,
) -> AzimuthStats:
    """Dominant lateral azimuth of horizontal wells whose stick lies within
    `buffer_ft` of the AOI, from each well's landing-point -> bottom-hole bearing
    (the producing-leg direction). This is the operative survey-grid azimuth.

    Azimuth is AXIAL — a lateral and its reverse describe the same grid line — so
    the average is a circular mean of the DOUBLED angles, folded back to
    [0, 180). The mean resultant length R is reported as `coherence`: ~1 means a
    tight, single-grid block; a low value means the AOI straddles survey blocks
    with different rotations (don't trust one azimuth). `formation` is normally
    left None — the grid doesn't change by bench, so all benches maximise the
    sample."""
    aoi = parcel_to_ewkt_4326(parcel)
    buffer_m = buffer_ft / FT_PER_M
    clauses = [
        "w.is_horizontal",
        "w.landing_point_lat IS NOT NULL", "w.landing_point_lon IS NOT NULL",
        "w.bhl_lat IS NOT NULL", "w.bhl_lon IS NOT NULL",
        "w.wellstick_geom IS NOT NULL",
        "ST_DWithin(w.wellstick_geom::geography, ST_GeogFromText(%(aoi)s), %(buffer_m)s)",
        # require a real lateral (LP and BHL far enough apart for a meaningful bearing)
        "ST_Distance(ST_SetSRID(ST_MakePoint(w.landing_point_lon, w.landing_point_lat),4326)::geography,"
        " ST_SetSRID(ST_MakePoint(w.bhl_lon, w.bhl_lat),4326)::geography) >= %(min_lat_m)s",
    ]
    params: dict = {"aoi": aoi, "buffer_m": buffer_m, "min_lat_m": _AZIMUTH_MIN_LATERAL_M}
    if formation is not None:
        clauses.append("w.formation_blueox = %(formation)s")
        params["formation"] = formation
    with conn.cursor() as cur:
        cur.execute(
            "SELECT degrees(ST_Azimuth("
            "  ST_SetSRID(ST_MakePoint(w.landing_point_lon, w.landing_point_lat),4326)::geography,"
            "  ST_SetSRID(ST_MakePoint(w.bhl_lon, w.bhl_lat),4326)::geography))::float "
            "FROM curated.wells_enriched w WHERE " + " AND ".join(clauses),
            params,
        )
        bearings = [row[0] for row in cur.fetchall() if row[0] is not None]

    n = len(bearings)
    if n == 0:
        return AzimuthStats(wells=0, azimuth_deg=None, coherence=0.0, circ_std_deg=None,
                            confident=False,
                            note=f"no horizontal laterals within {buffer_ft:.0f} ft of the AOI")

    # axial circular mean: double the angles so 10 deg and 190 deg reinforce
    s = sum(math.sin(math.radians(2 * b)) for b in bearings) / n
    c = sum(math.cos(math.radians(2 * b)) for b in bearings) / n
    R = math.hypot(s, c)                                   # mean resultant length
    az = (math.degrees(math.atan2(s, c)) / 2.0) % 180.0    # fold back to [0,180)
    # circular std (Mardia) on the axial scale, reported in real (halved) degrees
    circ_std = math.degrees(math.sqrt(-2.0 * math.log(R))) / 2.0 if R > 1e-9 else None
    confident = n >= _AZIMUTH_MIN_WELLS and R >= _AZIMUTH_MIN_COHERENCE
    note = (f"{n} laterals; grid azimuth {az:.1f}° "
            f"(coherence {R:.2f}"
            + (f", circ-std {circ_std:.1f}°" if circ_std is not None else "") + ")")
    if not confident:
        note += (f"  [LOW COHERENCE < {_AZIMUTH_MIN_COHERENCE:.2f} — likely straddling survey "
                 f"blocks; fall back to the parcel long axis]" if n >= _AZIMUTH_MIN_WELLS
                 else f"  [only {n} laterals — too few to trust]")
    return AzimuthStats(wells=n, azimuth_deg=round(az, 1), coherence=round(R, 3),
                        circ_std_deg=round(circ_std, 1) if circ_std is not None else None,
                        confident=confident, note=note)


def section_azimuth(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    buffer_ft: float = 5280.0,
) -> float | None:
    """Convenience: the offset-well grid azimuth if it's confident, else None
    (so the caller falls back to the geometry core's parcel-long-axis default)."""
    st = lateral_azimuth_stats(conn, parcel, buffer_ft)
    return st.azimuth_deg if st.confident else None


@dataclass
class BenchInfo:
    """A developable bench discovered in/around a parcel, with evidence."""

    formation: str                  # formation_blueox code
    median_tvd_ft: float | None
    n_pdp: int                      # producing wells (proven; -> anduin TC route)
    n_pud: int                      # Novi PUD sticks
    n_res: int                      # Novi RES sticks (resource/edge of fairway)
    suggested_spacing_ft: float | None   # de-facto same-bench lateral spacing
    note: str = ""


def available_benches(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    buffer_ft: float = 1320.0,
) -> list[BenchInfo]:
    """Benches present in/around a parcel — the same evidence erebor shows for a
    unit: Novi intel PUD/RES sticks (via curated.intel_formation_blueox) plus PDP
    producers (curated.wells_enriched), keyed on formation_blueox. Each bench
    carries its median landing TVD and a suggested per-bench spacing derived from
    the de-facto nearest-neighbor distance between same-bench laterals (Bone Spring
    develops wider than Wolfcamp), so the wine-rack defaults match how the rock is
    actually developed. Buffer (default 1320 ft = ~1 spacing) catches immediate
    offsets just outside the unit."""
    aoi = parcel_to_ewkt_4326(parcel)
    buf_m = buffer_ft / FT_PER_M
    benches: dict[str, BenchInfo] = {}

    with conn.cursor() as cur:
        # Novi intel sticks (PUD/RES/PDP) carrying a formation_blueox. PUDs pass
        # the SAME reconciliation filter as _STICK_SQL (realized ones are already
        # drilled) so the bench menu counts match what the map/gun-barrel shows.
        cur.execute(
            """
            SELECT ifb.formation_blueox AS fb, il.category, COUNT(*) AS n,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY il.tvd) AS med_tvd
            FROM curated.intel_locations il
            JOIN curated.intel_formation_blueox ifb USING (stick_id)
            LEFT JOIN curated.reconciled_inventory ri USING (stick_id)
            WHERE il.wellstick_geom IS NOT NULL
              AND ifb.formation_blueox IS NOT NULL
              AND ST_DWithin(il.wellstick_geom::geography,
                             ST_GeogFromText(%(aoi)s), %(buf)s)
              AND (il.category <> 'PUD' OR ri.status IS NULL
                   OR ri.status IN ('remaining_pud', 'conflict'))
            GROUP BY 1, 2
            """,
            {"aoi": aoi, "buf": buf_m},
        )
        for fb, category, n, med_tvd in cur.fetchall():
            b = benches.setdefault(fb, BenchInfo(fb, med_tvd, 0, 0, 0, None))
            if med_tvd is not None and b.median_tvd_ft is None:
                b.median_tvd_ft = med_tvd
            if category == "PUD":
                b.n_pud += n
            elif category == "RES":
                b.n_res += n
            elif category == "PDP":
                b.n_pdp += n

        # PDP producers (authoritative for proven benches + their median TVD)
        cur.execute(
            """
            SELECT formation_blueox AS fb, COUNT(*) AS n,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY tvd_ft) AS med_tvd
            FROM curated.wells_enriched
            WHERE is_horizontal AND formation_blueox IS NOT NULL
              AND tvd_ft IS NOT NULL AND wellstick_geom IS NOT NULL
              AND ST_DWithin(wellstick_geom::geography,
                             ST_GeogFromText(%(aoi)s), %(buf)s)
            GROUP BY 1
            """,
            {"aoi": aoi, "buf": buf_m},
        )
        for fb, n, med_tvd in cur.fetchall():
            b = benches.setdefault(fb, BenchInfo(fb, med_tvd, 0, 0, 0, None))
            b.n_pdp = max(b.n_pdp, n)                  # producers, not intel-PDP sticks
            if med_tvd is not None:
                b.median_tvd_ft = med_tvd              # producer TVD supersedes

        # de-facto per-bench spacing: project same-bench stick centroids onto the
        # cross-section axis (perpendicular to the grid azimuth) and take the
        # median gap between distinct rows. Robust to near-duplicate/stacked
        # sticks (same lateral as PUD+RES, report versions), which a raw nearest-
        # neighbor distance double-counts as ~0 ft. No grid azimuth (no offset
        # laterals) -> skip: projecting on a fake az=0 axis fabricates spacing.
        az = lateral_azimuth_stats(conn, parcel, buffer_ft=max(buffer_ft, 5280.0)).azimuth_deg
        cross: dict[str, list[float]] = {}
        if az is not None:
            perp = cross_axis(az)                      # canonical cross axis (E, N)
            cur.execute(
                f"""
                SELECT ifb.formation_blueox AS fb,
                       ST_X(ST_Transform(ST_Centroid(il.wellstick_geom), {WORK_EPSG})) AS x,
                       ST_Y(ST_Transform(ST_Centroid(il.wellstick_geom), {WORK_EPSG})) AS y
                FROM curated.intel_locations il
                JOIN curated.intel_formation_blueox ifb USING (stick_id)
                WHERE ifb.formation_blueox IS NOT NULL AND il.wellstick_geom IS NOT NULL
                  AND ST_DWithin(il.wellstick_geom::geography,
                                 ST_GeogFromText(%(aoi)s), %(buf)s)
                """,
                {"aoi": aoi, "buf": buf_m},
            )
            for fb, x, y in cur.fetchall():
                if fb in benches and x is not None and y is not None:
                    cross.setdefault(fb, []).append((x * perp[0] + y * perp[1]) * FT_PER_M)

    for fb, vals in cross.items():
        rows = sorted({round(v / 50.0) * 50.0 for v in vals})       # dedup rows to ~50 ft
        gaps = [b - a for a, b in zip(rows, rows[1:]) if (b - a) >= 200.0]  # skip duplicates
        if gaps:
            benches[fb].suggested_spacing_ft = round(_median(gaps), 0)

    out = sorted(benches.values(),
                 key=lambda b: (b.median_tvd_ft if b.median_tvd_ft is not None else 1e9))
    for b in out:
        srcs = []
        if b.n_pdp:
            srcs.append(f"{b.n_pdp} PDP")
        if b.n_pud:
            srcs.append(f"{b.n_pud} PUD")
        if b.n_res:
            srcs.append(f"{b.n_res} RES")
        sp = f", ~{b.suggested_spacing_ft:.0f} ft spacing" if b.suggested_spacing_ft else ""
        b.note = (f"{b.formation} @ {b.median_tvd_ft:,.0f} ft TVD "
                  f"({', '.join(srcs) or 'no control'}{sp})"
                  if b.median_tvd_ft is not None else f"{b.formation} ({', '.join(srcs)})")
    return out


# Producing horizontals only (aligned with the erebor_locations PDP arm): a
# permit/DUC isn't PDP context. The api10 regex guarantees a stable well_name
# (culls are keyed on it); ORDER BY makes re-fetches deterministic.
# Producing-leg geometry: landing point -> BHL when the header carries both, else
# RECONSTRUCTED from the wellstick — heel = the point `lateral_length_ft` back
# from the stick's end (work-CRS interpolation), toe = the stick's endpoint.
# The vendor header drops LP/BHL coords on some wells (e.g. 3 of 6 CALYPSO
# 29-16-9 producers) whose sticks are fine; requiring LP+BHL silently erased
# them from the unit inventory (bro_time 1 4-9 showed 4 of 7 producers).
_PDP_SQL = f"""
    WITH src AS (
        SELECT formation_blueox, tvd_ft, lateral_length_ft, api10,
               landing_point_lon, landing_point_lat, bhl_lon, bhl_lat,
               ST_LineMerge(wellstick_geom) AS ls,
               ST_Transform(ST_LineMerge(wellstick_geom), {WORK_EPSG}) AS ls_w
        FROM curated.wells_enriched
        WHERE is_horizontal AND formation_blueox IS NOT NULL
          AND first_production_date IS NOT NULL
          AND api10 ~ '^[0-9]+$'
          AND basin_blueox IN ('delaware', 'midland')
          AND wellstick_geom IS NOT NULL
          AND ST_DWithin(wellstick_geom::geography, ST_GeogFromText(%(aoi)s), %(buf)s)
    ),
    calc AS (
        SELECT *,
               GREATEST(0.0, LEAST(1.0,
                   1.0 - COALESCE(lateral_length_ft / {FT_PER_M},
                                  ST_Length(ls_w) * 0.5)
                         / NULLIF(ST_Length(ls_w), 0.0))) AS heel_frac
        FROM src
    )
    SELECT formation_blueox, tvd_ft, lateral_length_ft, api10,
           CASE WHEN landing_point_lon IS NOT NULL AND landing_point_lat IS NOT NULL
                THEN landing_point_lon
                ELSE ST_X(ST_Transform(ST_LineInterpolatePoint(ls_w, heel_frac), 4326)) END,
           CASE WHEN landing_point_lon IS NOT NULL AND landing_point_lat IS NOT NULL
                THEN landing_point_lat
                ELSE ST_Y(ST_Transform(ST_LineInterpolatePoint(ls_w, heel_frac), 4326)) END,
           COALESCE(bhl_lon, ST_X(ST_EndPoint(ls))),
           COALESCE(bhl_lat, ST_Y(ST_EndPoint(ls)))
    FROM calc
    ORDER BY api10
"""

# PUD sticks are filtered through the §6 reconciliation (curated.reconciled_
# inventory): only genuinely-remaining inventory (remaining_pud), ambiguous
# (conflict), and NOT-YET-RECONCILED (no row — treat as remaining, don't
# silently drop) are drillable locations — realized_drift/realized_phantom are
# already drilled, so they're NOT shown. RES isn't reconciled (pass-through).
_STICK_SQL = """
    SELECT il.stick_id, ifb.formation_blueox, il.tvd, il.unique_id,
           lower(il.category), ri.status,
           ST_X(ST_StartPoint(ST_LineMerge(il.wellstick_geom))),
           ST_Y(ST_StartPoint(ST_LineMerge(il.wellstick_geom))),
           ST_X(ST_EndPoint(ST_LineMerge(il.wellstick_geom))),
           ST_Y(ST_EndPoint(ST_LineMerge(il.wellstick_geom)))
    FROM curated.intel_locations il
    JOIN curated.intel_formation_blueox ifb USING (stick_id)
    LEFT JOIN curated.reconciled_inventory ri USING (stick_id)
    WHERE il.category = ANY(%(cats)s) AND il.wellstick_geom IS NOT NULL
      AND ifb.formation_blueox IS NOT NULL
      AND ST_DWithin(il.wellstick_geom::geography, ST_GeogFromText(%(aoi)s), %(buf)s)
      AND (il.category = 'RES' OR ri.status IS NULL
           OR ri.status IN ('remaining_pud', 'conflict'))
    ORDER BY il.stick_id
"""


def _passthrough_well(fb, tvd, name, novi, category, h_lon, h_lat, t_lon, t_lat, az,
                      fallback_name, recon_status=None):
    """Build a single-leg InventoryWell from a warehouse lateral (heel->toe in
    lon/lat). Returns (well, cross_m) where cross_m is the well's work-CRS centroid
    for the cross-section projection; gunbarrel_x is set by the caller. Names must
    be STABLE across re-fetches (culls key on well_name), so `fallback_name` is
    derived from a warehouse key (stick_id), never from list position."""
    hx, hy = _to_work(h_lon, h_lat)
    tx, ty = _to_work(t_lon, t_lat)
    length_ft = math.hypot(tx - hx, ty - hy) * FT_PER_M
    leg = Leg(
        heel_xy=(round(hx, 2), round(hy, 2)), toe_xy=(round(tx, 2), round(ty, 2)),
        heel_lonlat=(round(h_lon, 6), round(h_lat, 6)),
        toe_lonlat=(round(t_lon, 6), round(t_lat, 6)),
        length_ft=round(length_ft, 1), gunbarrel_x_ft=0.0,   # set by caller
    )
    well = InventoryWell(
        scenario_id="", deal_id="", well_name=str(name or fallback_name),
        well_type="single", formation=fb,
        target_tvd_ft=float(tvd) if tvd else 0.0, lateral_azimuth_deg=round(az, 1),
        legs=[leg], turn=None,
        completed_lateral_ft=round(length_ft, 1), drilled_lateral_ft=round(length_ft, 1),
        nearest_neighbor_spacing_ft=0.0, setback_ft=0.0,
        category=category, novi_wellname=novi, recon_status=recon_status,
    )
    return well, ((hx + tx) / 2.0, (hy + ty) / 2.0)


def _classify_membership(
    items: list[tuple[InventoryWell, tuple[float, float]]],
    parcel: BaseGeometry,
    min_overlap_frac: float,
    context_radius_m: float | None,
) -> tuple[list[tuple[InventoryWell, tuple[float, float]]],
           list[tuple[InventoryWell, tuple[float, float]]]]:
    """Split fetched laterals into (kept, context). kept = unit membership: at
    least `min_overlap_frac` of the leg runs INSIDE the parcel (co-extent overlap,
    never min-distance) — a long lateral that merely clips the edge on its way to
    a neighbouring unit is excluded. context = PDP-only laterals that FAIL
    membership but lie within `context_radius_m` of the parcel: offset background
    for the gun-barrel/map, never persisted or exported. Pure (no DB) for tests."""
    kept: list[tuple[InventoryWell, tuple[float, float]]] = []
    context: list[tuple[InventoryWell, tuple[float, float]]] = []
    for well, cross in items:
        leg = well.legs[0]
        line = LineString([leg.heel_xy, leg.toe_xy])
        if line.length <= 0:
            continue
        if line.intersection(parcel).length / line.length >= min_overlap_frac:
            kept.append((well, cross))
        elif (context_radius_m is not None and well.category == "pdp"
              and line.distance(parcel) <= context_radius_m):
            context.append((well, cross))
    return kept, context


def inventory_from_warehouse(
    conn: psycopg.Connection,
    parcel: BaseGeometry,
    buffer_ft: float = 1320.0,
    categories: tuple[str, ...] = ("pdp", "pud", "res"),
    min_overlap_frac: float = 0.30,
    context_radius_ft: float | None = None,
) -> list[InventoryWell]:
    """Adopt the EXISTING inventory IN a parcel as InventoryWells — the curate-mode
    baseline. PDP producers (curated.wells_enriched, landing->bottom-hole leg) and
    Novi PUD/RES sticks (curated.intel_locations + intel_formation_blueox) become
    single-leg wells tagged by `category`. Unit membership is co-extent overlap
    (see _classify_membership); with `context_radius_ft`, near-parcel PDP laterals
    that fail membership come back flagged `context=True` (visual background only).
    gunbarrel_x is the CANONICAL cross-section offset — placement.cross_axis(az)
    from the parcel centroid, the same frame generated wells use, so curate,
    override and context populations overlay in one gun-barrel."""
    aoi = parcel_to_ewkt_4326(parcel)
    fetch_ft = max(buffer_ft, context_radius_ft or 0.0)
    buf_m = fetch_ft / FT_PER_M
    az = (lateral_azimuth_stats(conn, parcel, buffer_ft=max(fetch_ft, 5280.0))
          .azimuth_deg or 0.0)
    items: list[tuple[InventoryWell, tuple[float, float]]] = []

    with conn.cursor() as cur:
        if "pdp" in categories:
            cur.execute(_PDP_SQL, {"aoi": aoi, "buf": buf_m})
            for fb, tvd, _ll, api10, hlon, hlat, tlon, tlat in cur.fetchall():
                if None not in (hlon, hlat, tlon, tlat):
                    items.append(_passthrough_well(fb, tvd, api10, None, "pdp",
                                                   hlon, hlat, tlon, tlat, az,
                                                   fallback_name=api10))
        stick_cats = [c.upper() for c in categories if c in ("pud", "res")]
        if stick_cats:
            cur.execute(_STICK_SQL, {"aoi": aoi, "buf": buf_m, "cats": stick_cats})
            for sid, fb, tvd, uid, cat, status, hlon, hlat, tlon, tlat in cur.fetchall():
                if None not in (hlon, hlat, tlon, tlat):
                    items.append(_passthrough_well(fb, tvd, uid, uid, cat,
                                                   hlon, hlat, tlon, tlat, az,
                                                   fallback_name=f"{cat}-{sid}",
                                                   recon_status=status))

    context_m = (context_radius_ft / FT_PER_M) if context_radius_ft else None
    kept, context = _classify_membership(items, parcel, min_overlap_frac, context_m)
    for well, _ in context:
        well.context = True

    all_items = kept + context
    origin = (parcel.centroid.x, parcel.centroid.y)
    for well, cross in all_items:
        well.legs[0].gunbarrel_x_ft = round(gunbarrel_offset_ft(cross, az, origin), 1)
    return [w for w, _ in all_items]


def bench_summary(wells: list[InventoryWell]) -> list[BenchInfo]:
    """Bench menu derived from a kept inventory set, so the panel and the map agree
    exactly. Counts per category + median landing TVD per formation_blueox; spacing
    left None (Novi's pass-through layout is the baseline, nothing to seed)."""
    agg: dict[str, dict] = {}
    for w in wells:
        d = agg.setdefault(w.formation, {"pdp": 0, "pud": 0, "res": 0, "tvds": []})
        if w.category in ("pdp", "pud", "res"):
            d[w.category] += 1
        if w.target_tvd_ft:
            d["tvds"].append(w.target_tvd_ft)
    out: list[BenchInfo] = []
    for fb, d in agg.items():
        med = round(_median(d["tvds"]), 0) if d["tvds"] else None
        srcs = [f"{d[k]} {k.upper()}" for k in ("pdp", "pud", "res") if d[k]]
        note = (f"{fb} @ {med:,.0f} ft TVD ({', '.join(srcs)})"
                if med is not None else f"{fb} ({', '.join(srcs)})")
        out.append(BenchInfo(fb, med, d["pdp"], d["pud"], d["res"], None, note))
    out.sort(key=lambda b: b.median_tvd_ft if b.median_tvd_ft is not None else 1e9)
    return out

"""Narvi warehouse data layer (Phase 4, §7) — sources real numbers from the
oilgas warehouse to feed the pure-geometry core.

This module is the ONLY part of narvi that talks to PostgreSQL. The geometry
core (parcel / placement / generate) stays DB-free and unit-testable; this layer
turns hand-typed scenario inputs into data-driven ones:

  * landing TVD per `formation_blueox` from offset wells in the AOI (median +
    spread + a multimodality flag that warns when one bench code is hiding two
    distinct landing targets), and
  * a ready-to-use `Zone` list for `generate_wine_rack`.

Connection mirrors engineering_db/etl/db.py: env-var credentials from a
gitignored `.env`, with Supabase session settings (statement_timeout=0,
search_path including `extensions` so PostGIS resolves).

Landing TVD = `curated.wells_enriched.tvd_ft`; the bench code is the
TVD-corrected `formation_blueox` (see [[formation-blueox-crosswalk]]). Geometry
filtering uses `wellstick_geom` (SRID 4326) against the AOI as a geography so the
buffer is a true metric distance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from dotenv import load_dotenv
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from .parcel import WORK_EPSG
from .records import FT_PER_M, Zone

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


_SESSION_SETTINGS: tuple[str, ...] = (
    "SET statement_timeout = 0",
    "SET search_path TO public, extensions",
)

# parcel work CRS (UTM 13N, metres) -> WGS84 lon/lat for the spatial filter
_to_wgs = Transformer.from_crs(
    CRS.from_epsg(WORK_EPSG), CRS.from_epsg(4326), always_xy=True
).transform


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def _db_kwargs() -> dict[str, str]:
    return {
        "host": _required_env("DB_HOST"),
        "port": os.getenv("DB_PORT", "5432"),
        "dbname": _required_env("DB_NAME"),
        "user": _required_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "sslmode": os.getenv("DB_SSLMODE", "prefer"),
        "connect_timeout": os.getenv("DB_CONNECT_TIMEOUT", "30"),
        "keepalives": "1",
        "keepalives_idle": "30",
        "keepalives_interval": "10",
        "keepalives_count": "5",
    }


def get_connection() -> psycopg.Connection:
    """Open a psycopg (v3) connection with Supabase-friendly session settings."""
    conn = psycopg.connect(**_db_kwargs())
    with conn.cursor() as cur:
        for stmt in _SESSION_SETTINGS:
            cur.execute(stmt)
    conn.commit()
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

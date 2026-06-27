"""Narvi forecaster adapters (Phase 4, §7) — attach a production forecast + EUR
to each planned inventory well.

Two sources behind one shape (`Forecast`, tagged by `source`):

  * novi_intel  — Novi's ML forecast for the PUD/RES location, pulled from
    curated.intel_locations (EUR) + curated.intel_forecast (monthly streams).
    USABLE only where the deal parcel agrees with Novi's pad footprint; a gross
    mismatch (planned laterals that don't line up with Novi's sticks) makes the
    Novi number irrelevant, so it's gated on parcel<->pad overlap AND per-leg
    co-extent overlap (the reconciliation convention — overlap, never min-dist).
  * narvi_analog (built next) — an offset-well type curve from the warehouse,
    biased to bounded co-development; the always-available screening forecast.

DB-connected layer; import explicitly (the geometry core stays DB-free).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from .parcel import WORK_EPSG
from .records import FT_PER_M, InventoryWell, Leg
from .warehouse import parcel_to_ewkt_4326

# match tolerances: a planned leg "is" a Novi stick when a parallel stick lies
# within tol_ft and shares the depth band. 660 ft (half a 1320 ft spacing) keeps
# the next row's stick from being claimed; the TVD band keeps it on-bench.
_DEFAULT_TOL_FT = 660.0
_DEFAULT_TVD_BAND_FT = 750.0
_MIN_LEG_OVERLAP_FRAC = 0.5     # a leg matches a stick only above this co-extent
# pad-match gate thresholds on parcel coverage (area(parcel ∩ pads)/area(parcel))
_PAD_GOOD = 0.60
_PAD_PARTIAL = 0.25


@dataclass
class Forecast:
    """A production forecast + EUR for one planned well, from one source."""

    source: str                 # 'novi_intel' | 'narvi_analog'
    well_name: str
    eur_oil_bbl: float | None
    eur_gas_mcf: float | None
    eur_water_bbl: float | None
    eur_ngl_bbl: float | None
    eur_boe: float | None       # oil + gas/6 (+ ngl)
    horizon_months: int
    months: list[int] = field(default_factory=list)       # month index (mop)
    oil: list[float] = field(default_factory=list)        # per-month oil
    gas: list[float] = field(default_factory=list)        # per-month gas
    water: list[float] = field(default_factory=list)      # per-month water
    match: dict = field(default_factory=dict)             # provenance / match quality
    note: str = ""


@dataclass
class PadMatch:
    """Deal-level gate: does the parcel agree with Novi's pad footprint?"""

    quality: str                # 'good' | 'partial' | 'poor' | 'none'
    parcel_coverage: float      # area(parcel ∩ pads) / area(parcel)
    pad_coverage: float         # area(parcel ∩ pads) / area(pads ∩ neighborhood)
    iou: float                  # intersection-over-union
    pad_names: list[str]
    note: str = ""


def _leg_ewkt(leg: Leg) -> str:
    (h_lon, h_lat), (t_lon, t_lat) = leg.heel_lonlat, leg.toe_lonlat
    return f"SRID=4326;LINESTRING({h_lon} {h_lat}, {t_lon} {t_lat})"


def pad_match(conn: psycopg.Connection, parcel, basin: str) -> PadMatch:
    """Overlap of the deal parcel with the Novi pad polygons it touches. High
    parcel coverage => the deal footprint agrees with Novi's development (Novi's
    per-location forecast is a contender). Low => gross mismatch (e.g. Hecker);
    don't lean on the Novi number."""
    aoi = parcel_to_ewkt_4326(parcel)
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH parcel AS (SELECT ST_GeomFromEWKT(%(aoi)s) AS g),
            pads AS (
                SELECT ST_Union(p.geom) AS g,
                       array_agg(DISTINCT p.pad_name) AS names
                FROM raw_novi_intel.pads p, parcel
                WHERE p.basin = %(basin)s
                  AND p.geom IS NOT NULL
                  AND ST_Intersects(p.geom, parcel.g)
            )
            SELECT
                COALESCE(ST_Area(ST_Intersection(parcel.g, pads.g)::geography), 0),
                ST_Area(parcel.g::geography),
                COALESCE(ST_Area(pads.g::geography), 0),
                pads.names
            FROM parcel, pads
            """,
            {"aoi": aoi, "basin": basin},
        )
        inter, parcel_a, pad_a, names = cur.fetchone()

    names = [n for n in (names or []) if n]
    if not names or pad_a == 0:
        return PadMatch("none", 0.0, 0.0, 0.0, [],
                        note="no Novi pad polygons intersect the parcel")
    parcel_cov = inter / parcel_a if parcel_a else 0.0
    pad_cov = inter / pad_a if pad_a else 0.0
    union = parcel_a + pad_a - inter
    iou = inter / union if union else 0.0
    quality = ("good" if parcel_cov >= _PAD_GOOD
               else "partial" if parcel_cov >= _PAD_PARTIAL else "poor")
    note = (f"{quality}: parcel coverage {parcel_cov:.0%}, pad coverage {pad_cov:.0%}, "
            f"IoU {iou:.0%} across {len(names)} pad(s)")
    return PadMatch(quality, round(parcel_cov, 3), round(pad_cov, 3), round(iou, 3),
                    sorted(names), note)


def _match_leg(
    conn: psycopg.Connection, leg: Leg, target_tvd: float | None,
    basin: str, tol_ft: float, tvd_band_ft: float, exclude: list[str] | None = None,
) -> dict | None:
    """Find the best co-extent Novi PUD/RES stick for one planned leg (overlap,
    never min-distance). Returns the stick's id, EURs, and match stats, or None
    when nothing overlaps enough to trust. `exclude` skips Novi sticks already
    claimed by another planned leg so a stick is never double-counted."""
    tol_m = tol_ft / FT_PER_M
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH leg AS (SELECT ST_Transform(ST_GeomFromEWKT(%(leg)s), {WORK_EPSG}) AS g)
            SELECT il.unique_id, il.formation, il.tvd, il.ll_ft,
                   il.oil_eur, il.gas_eur, il.water_eur, il.ngl_eur,
                   ST_Length(ST_Intersection(
                       ST_Transform(il.wellstick_geom, {WORK_EPSG}),
                       ST_Buffer(leg.g, %(tol_m)s))) AS overlap_m,
                   ST_Length(ST_Transform(il.wellstick_geom, {WORK_EPSG})) AS stick_m,
                   ST_Length(leg.g) AS leg_m
            FROM curated.intel_locations il, leg
            WHERE il.basin = %(basin)s
              AND il.category IN ('PUD','RES')
              AND il.wellstick_geom IS NOT NULL
              AND ST_DWithin(ST_Transform(il.wellstick_geom, {WORK_EPSG}), leg.g, %(tol_m)s)
              AND (%(tvd)s IS NULL OR il.tvd IS NULL
                   OR abs(il.tvd - %(tvd)s) <= %(tvd_band)s)
              AND (%(excl)s::text[] IS NULL OR il.unique_id <> ALL(%(excl)s::text[]))
            ORDER BY overlap_m DESC, il.unique_id     -- deterministic on near-ties
            LIMIT 1
            """,
            {"leg": _leg_ewkt(leg), "tol_m": tol_m, "basin": basin,
             "tvd": target_tvd, "tvd_band": tvd_band_ft,
             "excl": list(exclude) if exclude else None},
        )
        row = cur.fetchone()
    if row is None:
        return None
    uid, formation, tvd, ll_ft, oil_eur, gas_eur, water_eur, ngl_eur, overlap_m, stick_m, leg_m = row
    denom = min(x for x in (stick_m, leg_m) if x) if (stick_m and leg_m) else (stick_m or leg_m)
    frac = (overlap_m / denom) if denom else 0.0
    if frac < _MIN_LEG_OVERLAP_FRAC:
        return None
    return {
        "novi_wellname": uid, "formation": formation, "tvd": tvd, "ll_ft": ll_ft,
        "oil_eur": oil_eur, "gas_eur": gas_eur, "water_eur": water_eur, "ngl_eur": ngl_eur,
        "overlap_frac": round(frac, 3),
        "tvd_delta": round(abs(tvd - target_tvd), 1) if (tvd and target_tvd) else None,
    }


def _monthly_stream(conn: psycopg.Connection, novi_wellname: str, basin: str):
    """Novi's monthly oil/gas/water stream for a stick (months-on-production)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT (ip_day / 30)::int AS mop,
                   COALESCE(oil, 0), COALESCE(gas, 0), COALESCE(water, 0)
            FROM raw_novi_intel.forecast
            WHERE basin = %(basin)s AND novi_wellname = %(wn)s
            ORDER BY ip_day
            """,
            {"basin": basin, "wn": novi_wellname},
        )
        rows = cur.fetchall()
    months = [r[0] for r in rows]
    return months, [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows]


def novi_forecast_for_well(
    conn: psycopg.Connection, well: InventoryWell, basin: str,
    tol_ft: float = _DEFAULT_TOL_FT, tvd_band_ft: float = _DEFAULT_TVD_BAND_FT,
    claimed: set[str] | None = None,
) -> Forecast | None:
    """Novi ML forecast for a planned well: match each producing leg to a Novi
    PUD/RES stick by co-extent overlap, then SUM the matched sticks' streams +
    EURs (a U-turn's two legs map to two Novi laterals). None if no leg matches —
    i.e. narvi's plan doesn't line up with Novi's locations here. `claimed` (if
    given) is the scenario-wide set of already-used Novi sticks; matched sticks
    are added to it so no stick's forecast is counted twice."""
    leg_matches = []
    months_ref: list[int] = []
    oil = gas = water = None
    eur_oil = eur_gas = eur_water = eur_ngl = 0.0
    have = False
    for leg in well.legs:
        m = _match_leg(conn, leg, well.target_tvd_ft, basin, tol_ft, tvd_band_ft,
                       exclude=sorted(claimed) if claimed else None)
        if m is None:
            continue
        have = True
        if claimed is not None:
            claimed.add(m["novi_wellname"])
        leg_matches.append(m)
        eur_oil += m["oil_eur"] or 0.0
        eur_gas += m["gas_eur"] or 0.0
        eur_water += m["water_eur"] or 0.0
        eur_ngl += m["ngl_eur"] or 0.0
        mn, o, g, w = _monthly_stream(conn, m["novi_wellname"], basin)
        if not mn:
            continue
        if oil is None:
            months_ref, oil, gas, water = mn, list(o), list(g), list(w)
        else:  # align by index and add (streams share the 30-day grid)
            for i in range(min(len(oil), len(o))):
                oil[i] += o[i]; gas[i] += g[i]; water[i] += w[i]

    if not have:
        return None
    oil = oil or []; gas = gas or []; water = water or []
    eur_boe = eur_oil + eur_gas / 6.0 + eur_ngl
    return Forecast(
        source="novi_intel", well_name=well.well_name,
        eur_oil_bbl=round(eur_oil, 1), eur_gas_mcf=round(eur_gas, 1),
        eur_water_bbl=round(eur_water, 1), eur_ngl_bbl=round(eur_ngl, 1),
        eur_boe=round(eur_boe, 1), horizon_months=len(months_ref),
        months=months_ref, oil=oil, gas=gas, water=water,
        match={"legs_matched": len(leg_matches), "legs_total": len(well.legs),
               "leg_matches": leg_matches},
        note=(f"Novi intel: {len(leg_matches)}/{len(well.legs)} legs matched; "
              f"EUR {eur_oil:,.0f} bo / {eur_gas:,.0f} mcf / {eur_ngl:,.0f} ngl"),
    )


def forecast_scenario_novi(
    conn: psycopg.Connection, parcel, wells: list[InventoryWell], basin: str,
    tol_ft: float = _DEFAULT_TOL_FT, tvd_band_ft: float = _DEFAULT_TVD_BAND_FT,
) -> tuple[PadMatch, list[Forecast]]:
    """Gate on parcel<->pad agreement, then forecast each planned well from Novi
    intel. Returns the pad-match verdict + per-well forecasts (None entries are
    dropped). The pad gate is advisory: even a 'poor' gate runs per-well matching
    so you can see exactly how little lines up."""
    pm = pad_match(conn, parcel, basin)
    forecasts = []
    claimed: set[str] = set()   # Novi sticks already used (no double-counting)
    for w in wells:
        fc = novi_forecast_for_well(conn, w, basin, tol_ft, tvd_band_ft, claimed=claimed)
        if fc is not None:
            forecasts.append(fc)
    return pm, forecasts

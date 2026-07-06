"""Narvi scenario persistence (Phase 4, §7) — write generated inventory back to
the warehouse and reload it.

Scenarios persist to a `narvi` schema in the oilgas DB (DDL in narvi/sql/
01_scenario.sql). Each well is stored with real PostGIS geometry (WGS84) for the
map plus a `detail` jsonb that round-trips the full InventoryWell record, so a
saved scenario reloads byte-for-byte as generated. This is the hand-off surface
to the forecasters (anduin TC / erebor ML read completed_lateral_ft + geometry).

Like narvi.warehouse, this is a DB-connected layer kept out of the pure geometry
core — import it explicitly.
"""

from __future__ import annotations

import os
from dataclasses import asdict

import psycopg
from psycopg.types.json import Jsonb
from shapely.geometry.base import BaseGeometry

from .records import InventoryWell, Leg, ScenarioParams, Turn
from .warehouse import parcel_to_ewkt_4326

_SCHEMA_SQL = os.path.join(os.path.dirname(__file__), "..", "..", "sql", "01_scenario.sql")


def _split_statements(sql_text: str) -> list[str]:
    """Split a (simple, no dollar-quoting) DDL script into statements on the
    semicolons that actually terminate a statement — i.e. ignoring ';' inside
    single-quoted string literals (our COMMENT strings contain one) and line
    comments. Good enough for this controlled DDL; not a general SQL parser."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql_text.splitlines())
    stmts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in no_comments:
        if ch == "'":
            in_str = not in_str
            buf.append(ch)
        elif ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def apply_schema(conn: psycopg.Connection, sql_path: str = _SCHEMA_SQL) -> None:
    """Create the `narvi` schema + tables if absent (idempotent)."""
    with open(sql_path, "r", encoding="utf-8") as fh:
        stmts = _split_statements(fh.read())
    with conn.cursor() as cur:
        for stmt in stmts:
            cur.execute(stmt)
    conn.commit()


def _legs_ewkt(well: InventoryWell) -> str:
    """Producing legs as a 4326 MULTILINESTRING (one part per leg, heel->toe)."""
    parts = []
    for leg in well.legs:
        (h_lon, h_lat), (t_lon, t_lat) = leg.heel_lonlat, leg.toe_lonlat
        parts.append(f"({h_lon} {h_lat}, {t_lon} {t_lat})")
    return "SRID=4326;MULTILINESTRING(" + ", ".join(parts) + ")"


def _turn_ewkt(well: InventoryWell) -> str | None:
    """The non-producing turn arc as a 4326 LINESTRING (None for singles)."""
    if not well.turn:
        return None
    pts = ", ".join(f"{lon} {lat}" for lon, lat in well.turn.arc_lonlat)
    return f"SRID=4326;LINESTRING({pts})"


def save_scenario(
    conn: psycopg.Connection,
    deal_id: str,
    scenario_id: str,
    parcel: BaseGeometry,
    params: ScenarioParams,
    wells: list[InventoryWell],
    summary: dict | None = None,
    name: str | None = None,
) -> int:
    """Upsert a scenario header + replace its inventory wells. Returns the well
    count written. A re-save of the same (deal_id, scenario_id) overwrites the
    prior run (wells are deleted via ON DELETE CASCADE through the header refresh
    of child rows). Caller controls the transaction; this commits on success."""
    aoi = parcel_to_ewkt_4326(parcel)
    # the resolved azimuth actually used (params.azimuth_deg may be None when auto)
    resolved_az = wells[0].lateral_azimuth_deg if wells else params.azimuth_deg
    total_legs = sum(len(w.legs) for w in wells)
    header = {
        "deal_id": deal_id, "scenario_id": scenario_id, "name": name,
        "well_type": params.well_type, "objective": params.objective,
        "spacing_ft": params.spacing_ft, "setback_ft": params.setback_ft,
        "setback_ns_ft": params.setback_ns_ft, "setback_ew_ft": params.setback_ew_ft,
        "azimuth_deg": resolved_az, "min_lateral_ft": params.min_lateral_ft,
        "uturn_min_leg_to_leg_ft": params.uturn_min_leg_to_leg_ft,
        "total_wells": len(wells), "total_legs": total_legs,
        "total_completed_ft": round(sum(w.completed_lateral_ft for w in wells), 1),
        "total_drilled_ft": round(sum(w.drilled_lateral_ft for w in wells), 1),
        "params": Jsonb(asdict(params)),
        "summary": Jsonb(summary) if summary is not None else None,
        "aoi": aoi,
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO narvi.scenario (
                deal_id, scenario_id, name, well_type, objective, spacing_ft,
                setback_ft, setback_ns_ft, setback_ew_ft, azimuth_deg,
                min_lateral_ft, uturn_min_leg_to_leg_ft, total_wells, total_legs,
                total_completed_ft, total_drilled_ft, params, summary, aoi_geom,
                updated_at)
            VALUES (
                %(deal_id)s, %(scenario_id)s, %(name)s, %(well_type)s, %(objective)s,
                %(spacing_ft)s, %(setback_ft)s, %(setback_ns_ft)s, %(setback_ew_ft)s,
                %(azimuth_deg)s, %(min_lateral_ft)s, %(uturn_min_leg_to_leg_ft)s,
                %(total_wells)s, %(total_legs)s, %(total_completed_ft)s,
                %(total_drilled_ft)s, %(params)s, %(summary)s,
                ST_GeomFromEWKT(%(aoi)s), NOW())
            ON CONFLICT (deal_id, scenario_id) DO UPDATE SET
                name = EXCLUDED.name, well_type = EXCLUDED.well_type,
                objective = EXCLUDED.objective, spacing_ft = EXCLUDED.spacing_ft,
                setback_ft = EXCLUDED.setback_ft, setback_ns_ft = EXCLUDED.setback_ns_ft,
                setback_ew_ft = EXCLUDED.setback_ew_ft, azimuth_deg = EXCLUDED.azimuth_deg,
                min_lateral_ft = EXCLUDED.min_lateral_ft,
                uturn_min_leg_to_leg_ft = EXCLUDED.uturn_min_leg_to_leg_ft,
                total_wells = EXCLUDED.total_wells, total_legs = EXCLUDED.total_legs,
                total_completed_ft = EXCLUDED.total_completed_ft,
                total_drilled_ft = EXCLUDED.total_drilled_ft,
                params = EXCLUDED.params, summary = EXCLUDED.summary,
                aoi_geom = EXCLUDED.aoi_geom, updated_at = NOW()
            """,
            header,
        )
        # replace child wells (the prior run's rows, if any)
        cur.execute(
            "DELETE FROM narvi.inventory_well WHERE deal_id = %s AND scenario_id = %s",
            (deal_id, scenario_id),
        )
        for w in wells:
            cur.execute(
                """
                INSERT INTO narvi.inventory_well (
                    deal_id, scenario_id, well_name, well_type, formation,
                    target_tvd_ft, lateral_azimuth_deg, n_legs, completed_lateral_ft,
                    drilled_lateral_ft, nearest_neighbor_spacing_ft, setback_ft,
                    turn_radius_ft, turn_dls_deg_per_100ft, turn_arc_ft,
                    legs_geom, turn_geom, detail)
                VALUES (
                    %(deal_id)s, %(scenario_id)s, %(well_name)s, %(well_type)s,
                    %(formation)s, %(target_tvd_ft)s, %(lateral_azimuth_deg)s,
                    %(n_legs)s, %(completed_lateral_ft)s, %(drilled_lateral_ft)s,
                    %(spacing)s, %(setback_ft)s, %(turn_radius_ft)s,
                    %(turn_dls)s, %(turn_arc_ft)s,
                    ST_GeomFromEWKT(%(legs)s), ST_GeomFromEWKT(%(turn)s), %(detail)s)
                """,
                {
                    "deal_id": deal_id, "scenario_id": scenario_id,
                    "well_name": w.well_name, "well_type": w.well_type,
                    "formation": w.formation, "target_tvd_ft": w.target_tvd_ft,
                    "lateral_azimuth_deg": w.lateral_azimuth_deg, "n_legs": len(w.legs),
                    "completed_lateral_ft": w.completed_lateral_ft,
                    "drilled_lateral_ft": w.drilled_lateral_ft,
                    "spacing": w.nearest_neighbor_spacing_ft, "setback_ft": w.setback_ft,
                    "turn_radius_ft": w.turn.radius_ft if w.turn else None,
                    "turn_dls": w.turn.dls_deg_per_100ft if w.turn else None,
                    "turn_arc_ft": w.turn.arc_ft if w.turn else None,
                    "legs": _legs_ewkt(w), "turn": _turn_ewkt(w),
                    "detail": Jsonb(asdict(w)),
                },
            )
    conn.commit()
    return len(wells)


def _well_from_detail(detail: dict) -> InventoryWell:
    """Reconstruct an InventoryWell from its stored `detail` jsonb (lists ->
    tuples for the coordinate pairs, matching what generate.py produces)."""
    legs = [
        Leg(
            heel_xy=tuple(d["heel_xy"]), toe_xy=tuple(d["toe_xy"]),
            heel_lonlat=tuple(d["heel_lonlat"]), toe_lonlat=tuple(d["toe_lonlat"]),
            length_ft=d["length_ft"], gunbarrel_x_ft=d["gunbarrel_x_ft"],
        )
        for d in detail["legs"]
    ]
    t = detail.get("turn")
    turn = (
        Turn(
            arc_xy=[tuple(p) for p in t["arc_xy"]],
            arc_lonlat=[tuple(p) for p in t["arc_lonlat"]],
            radius_ft=t["radius_ft"], arc_ft=t["arc_ft"],
            dls_deg_per_100ft=t["dls_deg_per_100ft"],
        )
        if t else None
    )
    return InventoryWell(
        scenario_id=detail["scenario_id"], deal_id=detail["deal_id"],
        well_name=detail["well_name"], well_type=detail["well_type"],
        formation=detail["formation"], target_tvd_ft=detail["target_tvd_ft"],
        lateral_azimuth_deg=detail["lateral_azimuth_deg"], legs=legs, turn=turn,
        completed_lateral_ft=detail["completed_lateral_ft"],
        drilled_lateral_ft=detail["drilled_lateral_ft"],
        nearest_neighbor_spacing_ft=detail["nearest_neighbor_spacing_ft"],
        setback_ft=detail["setback_ft"],
        # provenance — needed for the curate baseline (Novi pass-through) to reload
        # faithfully; defaults keep generated/override wells unchanged.
        category=detail.get("category", "generated"),
        novi_wellname=detail.get("novi_wellname"),
        edited=detail.get("edited", False),
        recon_status=detail.get("recon_status"),
        context=detail.get("context", False),
    )


def load_scenario(
    conn: psycopg.Connection, deal_id: str, scenario_id: str
) -> tuple[dict | None, list[InventoryWell]]:
    """Reload a saved scenario: (header dict, inventory wells). Header is None if
    the scenario doesn't exist. Wells are reconstructed exactly from `detail`."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT deal_id, scenario_id, name, well_type, objective, spacing_ft,
                   setback_ft, setback_ns_ft, setback_ew_ft, azimuth_deg,
                   min_lateral_ft, total_wells, total_legs, total_completed_ft,
                   total_drilled_ft, summary, created_at, updated_at
            FROM narvi.scenario WHERE deal_id = %s AND scenario_id = %s
            """,
            (deal_id, scenario_id),
        )
        row = cur.fetchone()
        if row is None:
            return None, []
        cols = [c.name for c in cur.description]
        header = dict(zip(cols, row))

        cur.execute(
            "SELECT detail FROM narvi.inventory_well "
            "WHERE deal_id = %s AND scenario_id = %s ORDER BY well_uid",
            (deal_id, scenario_id),
        )
        wells = [_well_from_detail(r[0]) for r in cur.fetchall()]
    return header, wells


def list_scenarios(conn: psycopg.Connection, deal_id: str | None = None) -> list[dict]:
    """List saved scenarios (optionally filtered to one deal), newest first."""
    sql = (
        "SELECT deal_id, scenario_id, name, well_type, objective, total_wells, "
        "total_legs, total_completed_ft, azimuth_deg, updated_at "
        "FROM narvi.scenario "
    )
    params: tuple = ()
    if deal_id is not None:
        sql += "WHERE deal_id = %s "
        params = (deal_id,)
    sql += "ORDER BY updated_at DESC"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def delete_scenario(conn: psycopg.Connection, deal_id: str, scenario_id: str) -> None:
    """Delete a scenario and its inventory wells (CASCADE)."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM narvi.scenario WHERE deal_id = %s AND scenario_id = %s",
            (deal_id, scenario_id),
        )
    conn.commit()

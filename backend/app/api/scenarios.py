"""Scenario persistence — list / load / save / delete generated inventory in the
narvi schema. Save regenerates server-side from the same GenerateRequest, then
persists, so the client never round-trips the geometry."""

from __future__ import annotations

import json
from dataclasses import replace

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from narvi import gunbarrel_data, persist, scenario_geojson

from ..deps import get_conn
from ..engine import run_generate
from ..models import SaveScenarioRequest, ScenarioSummary

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios(
    deal_id: str | None = None, conn: psycopg.Connection = Depends(get_conn)
) -> list[ScenarioSummary]:
    persist.apply_schema(conn)
    return [
        ScenarioSummary(
            deal_id=r["deal_id"], scenario_id=r["scenario_id"], name=r["name"],
            well_type=r["well_type"], objective=r["objective"],
            total_wells=r["total_wells"], total_legs=r["total_legs"],
            total_completed_ft=r["total_completed_ft"], azimuth_deg=r["azimuth_deg"],
        )
        for r in persist.list_scenarios(conn, deal_id)
    ]


@router.post("")
def save(req: SaveScenarioRequest, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    try:
        parcel, p, wells, window, summary, notes = run_generate(req.generate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    p = replace(p, deal_id=req.deal_id, scenario_id=req.scenario_id)
    persist.apply_schema(conn)
    n = persist.save_scenario(
        conn, req.deal_id, req.scenario_id, parcel, p, wells,
        summary={"note": summary, "warehouse_notes": notes}, name=req.name)
    return {"saved_wells": n, "deal_id": req.deal_id, "scenario_id": req.scenario_id}


@router.get("/{deal_id}/{scenario_id}")
def load(
    deal_id: str, scenario_id: str, conn: psycopg.Connection = Depends(get_conn)
) -> dict:
    header, wells = persist.load_scenario(conn, deal_id, scenario_id)
    if header is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    fc = scenario_geojson(None, None, wells)
    with conn.cursor() as cur:  # rebuild the parcel outline from the stored AOI
        cur.execute(
            "SELECT ST_AsGeoJSON(aoi_geom) FROM narvi.scenario "
            "WHERE deal_id = %s AND scenario_id = %s",
            (deal_id, scenario_id),
        )
        row = cur.fetchone()
    if row and row[0]:
        fc["features"].insert(
            0, {"type": "Feature", "geometry": json.loads(row[0]),
                "properties": {"kind": "parcel"}})
    return {"header": header, "geojson": fc, "gunbarrel": gunbarrel_data(wells)}


@router.delete("/{deal_id}/{scenario_id}")
def delete(
    deal_id: str, scenario_id: str, conn: psycopg.Connection = Depends(get_conn)
) -> dict:
    persist.delete_scenario(conn, deal_id, scenario_id)
    return {"deleted": True, "deal_id": deal_id, "scenario_id": scenario_id}

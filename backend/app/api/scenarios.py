"""Scenario persistence — list / load / save / delete generated inventory in the
narvi schema. Save regenerates server-side from the same GenerateRequest, then
persists, so the client never round-trips the geometry."""

from __future__ import annotations

import json
from dataclasses import replace

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from narvi import gunbarrel_data, parcel_from_geojson, persist, scenario_geojson
from narvi.records import ScenarioParams
from narvi.warehouse import inventory_from_warehouse

from ..deps import get_conn
from ..engine import run_generate
from ..models import SaveCurateRequest, SaveScenarioRequest, ScenarioSummary

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

_ACRE_M2 = 4046.8564224


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios(
    deal_id: str | None = None, conn: psycopg.Connection = Depends(get_conn)
) -> list[ScenarioSummary]:
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
    # Bake culls into the saved plan: culled wells are dropped from the persisted
    # rows entirely (not just hidden) so the narvi hand-off surface the forecasters
    # read never carries a well the planner removed. Culling keys on well_name.
    culled = set(req.culled_wells)
    if culled:
        wells = [w for w in wells if w.well_name not in culled]
    n = persist.save_scenario(
        conn, req.deal_id, req.scenario_id, parcel, p, wells,
        # `generate` = the exact request recipe (minus the parcel, which reloads
        # from the stored AOI) so the client can restore an EDITABLE override
        # state on load — params, mode, and per-bench zones included.
        summary={"note": summary, "warehouse_notes": notes,
                 "generate": req.generate.model_dump(mode="json", exclude={"parcel"})},
        name=req.name)
    return {"saved_wells": n, "deal_id": req.deal_id, "scenario_id": req.scenario_id}


@router.post("/curate")
def save_curate(req: SaveCurateRequest, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    """Persist a curated Novi-inventory baseline (the kept-PUD/PDP/RES set) directly,
    without a generate run. Re-derives the parcel's inventory server-side and keeps
    the wells whose bench is selected and whose category is active."""
    parcel = parcel_from_geojson(req.parcel)
    cats = tuple(c for c in ("pdp", "pud", "res") if c in req.categories)
    wells = inventory_from_warehouse(conn, parcel, req.buffer_ft, cats)
    kept = set(req.kept_benches)
    culled = set(req.culled_wells)
    wells = [w for w in wells if w.formation in kept and w.well_name not in culled]
    if not wells:
        raise HTTPException(status_code=400, detail="no inventory wells in the kept selection")
    for w in wells:
        w.deal_id, w.scenario_id = req.deal_id, req.scenario_id
    # synthetic header params: a curate baseline is pass-through singles, not a run
    p = ScenarioParams(
        scenario_id=req.scenario_id, deal_id=req.deal_id, formation="", target_tvd_ft=0.0,
        well_type="single", objective="max_lateral", spacing_ft=0.0, setback_ft=0.0,
        azimuth_deg=None, min_lateral_ft=0.0)
    n = persist.save_scenario(
        conn, req.deal_id, req.scenario_id, parcel, p, wells,
        summary={"mode": "curate", "kept_benches": req.kept_benches,
                 "categories": list(cats), "culled_wells": req.culled_wells}, name=req.name)
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
    parcel_info = None
    if row and row[0]:
        aoi = json.loads(row[0])
        fc["features"].insert(
            0, {"type": "Feature", "geometry": aoi, "properties": {"kind": "parcel"}})
        # ParcelInfo-shaped, so the client can re-select the parcel when
        # restoring a saved scenario. label MUST be the deal slug: the client
        # derives deal_id from the parcel label on save, so a name-derived
        # label would fork re-saves into a new deal.
        geom = parcel_from_geojson(aoi)
        parcel_info = {"label": deal_id,
                       "area_ac": round(geom.area / _ACRE_M2, 1), "geojson": aoi}
    return {"header": header, "geojson": fc, "gunbarrel": gunbarrel_data(wells),
            "parcel": parcel_info}


@router.delete("/{deal_id}/{scenario_id}")
def delete(
    deal_id: str, scenario_id: str, conn: psycopg.Connection = Depends(get_conn)
) -> dict:
    persist.delete_scenario(conn, deal_id, scenario_id)
    return {"deleted": True, "deal_id": deal_id, "scenario_id": scenario_id}

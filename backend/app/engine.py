"""Generation orchestration shared by the /generate and /scenarios endpoints.

Turns a GenerateRequest (parcel GeoJSON + params + optional warehouse sourcing)
into placed inventory wells. The warehouse connection is opened lazily — only
when the request asks to source TVDs or the grid azimuth — so a pure geometry
generate never touches the DB.
"""

from __future__ import annotations

from dataclasses import replace

from narvi import (
    generate_scenario,
    generate_wine_rack,
    gunbarrel_data,
    parcel_from_geojson,
    scenario_geojson,
)
from narvi.warehouse import (
    apply_handoff_support,
    get_connection,
    section_azimuth,
    zones_from_warehouse,
)

from .models import GenerateRequest, GenerateResponse


def run_generate(req: GenerateRequest):
    """-> (parcel, params, wells, window, summary, notes). Raises ValueError on a
    bad request (caller maps to HTTP 400)."""
    parcel = parcel_from_geojson(req.parcel)
    p = req.params.to_narvi()
    notes: list[str] = []

    # A stipulated W/E anchor line defines the azimuth (laterals parallel to that
    # lease line), so we don't source a grid azimuth — the engine derives it from the
    # edge. Only hit the DB for the azimuth when no line anchor is chosen.
    anchor_defines_az = p.anchor in ("west", "east")
    needs_db = req.score_support or (req.source_azimuth and not anchor_defines_az) or (
        req.mode == "winerack" and req.source_tvd and not req.zones)
    conn = get_connection() if needs_db else None
    try:
        if anchor_defines_az:
            notes.append(f"grid azimuth from the {p.anchor} lease line "
                         f"(laterals parallel to the setback)")
        elif req.source_azimuth and p.azimuth_deg is None:
            az = section_azimuth(conn, parcel, req.buffer_ft)
            if az is not None:
                p = replace(p, azimuth_deg=az)
                notes.append(f"adopted offset-well grid azimuth {az:.1f} deg")
            else:
                notes.append("grid azimuth not confident; using parcel long axis")

        if req.mode == "winerack":
            if req.zones:
                zones = [z.to_narvi() for z in req.zones]
            elif req.source_tvd and req.formations:
                zones, stats = zones_from_warehouse(
                    conn, parcel, req.formations, req.buffer_ft, split_multimodal=True)
                notes += [s.note for s in stats]
            else:
                raise ValueError("winerack mode needs `zones`, or `source_tvd` + `formations`")
            if not zones:
                raise ValueError("no benches with sufficient warehouse control in the AOI")
            wells, window, rep = generate_wine_rack(parcel, p, zones)
            summary = rep.note
        else:
            wells, window, feas = generate_scenario(parcel, p)
            summary = feas.note

        # Handoff classification (PDP/PUD/UPSIDE for the workbook inventory
        # tab): score generated sticks against the sql/30 qualifying-PDP gate
        # and derive categories, so the UI shows what the drop will say.
        if req.score_support:
            apply_handoff_support(conn, wells)
            n_pud = sum(1 for w in wells if w.handoff_category == "PUD")
            notes.append(
                f"handoff scoring: {n_pud} PUD / {len(wells) - n_pud} UPSIDE "
                f"(pdp_count_3mi >= 3 -> PUD; override per well before save)"
            )
    finally:
        if conn is not None:
            conn.close()

    return parcel, p, wells, window, summary, notes


def generate_response(req: GenerateRequest) -> GenerateResponse:
    parcel, p, wells, window, summary, notes = run_generate(req)
    az = wells[0].lateral_azimuth_deg if wells else p.azimuth_deg
    return GenerateResponse(
        mode=req.mode, placed_wells=len(wells),
        placed_legs=sum(len(w.legs) for w in wells),
        azimuth_deg=az, summary=summary, warehouse_notes=notes,
        geojson=scenario_geojson(parcel, window, wells),
        gunbarrel=gunbarrel_data(wells),
    )

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
from narvi.warehouse import get_connection, section_azimuth, zones_from_warehouse

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
    needs_db = (req.source_azimuth and not anchor_defines_az) or (
        req.mode == "winerack" and req.source_tvd and not req.zones)
    conn = get_connection() if needs_db else None
    sourced_az: float | None = None
    try:
        if anchor_defines_az:
            notes.append(f"grid azimuth from the {p.anchor} lease line "
                         f"(laterals parallel to the setback)")
        elif req.source_azimuth and p.azimuth_deg is None:
            az = section_azimuth(conn, parcel, req.buffer_ft)
            if az is not None:
                p = replace(p, azimuth_deg=az)
                sourced_az = az
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
        else:
            zones = None

        def _run(pp):
            if zones is not None:
                ws, win, rep = generate_wine_rack(parcel, pp, zones)
                return ws, win, rep.note
            ws, win, feas = generate_scenario(parcel, pp)
            return ws, win, feas.note

        wells, window, summary = _run(p)

        # Feasibility-aware fallback: a SOURCED grid azimuth that places nothing
        # (e.g. N-S grid on a half-mile-deep tract) is the app confidently doing
        # the wrong thing. Retry on the parcel long axis and say so LOUDLY —
        # cross-grid development is a real decision, so it's flagged, not silent.
        # A user-stipulated azimuth is never second-guessed (sourced_az only).
        if not wells and sourced_az is not None:
            p2 = replace(p, azimuth_deg=None)
            wells2, window2, summary2 = _run(p2)
            if wells2:
                p, wells, window, summary = p2, wells2, window2, summary2
                used = wells[0].lateral_azimuth_deg
                notes.append(
                    f"grid azimuth {sourced_az:.1f} deg places NO wells here — fell back "
                    f"to the parcel long axis ({used:.1f} deg). CROSS-GRID to offset "
                    f"development; set the azimuth override to force the grid.")
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

# Narvi — inventory-planning geometry core

Generates well-inventory scenarios (U-turn / single laterals) on a parcel, with
spatial attributes, for the Blue Ox app stack. Pure-geometry library now
(Phase 0, no DB); warehouse wiring + app shell + forecaster adapters come in
Phase 4. See `../narvi_buildout_plan.md` for the full plan.

**Scope:** locations + configuration + forecast only. Economics (deck / LOE /
capex / commercial terms) is intentionally out of scope — handed downstream.

## Status — slice 1 (single-lateral engine)

- [x] Parcel ingest (deal `.zip` shapefile → UTM 13N) + synthetic section
- [x] Drillable window (uniform setback)
- [x] Parallel single-lateral placement at spacing + azimuth, min-length filter
- [x] Feasibility report + inventory-well records (§5 subset) + gunbarrel x
- [ ] U-turn geometry (legs + turn arc, DLS, drilled vs completed) — slice 2
- [ ] Multi-zone wine-rack stagger — slice 3
- [ ] Asymmetric setbacks (edge-strip), objective toggle — slice 4

## Run the demo

```bash
.venv/Scripts/python.exe demo.py                  # synthetic 1-mile section
.venv/Scripts/python.exe demo.py path/to/deal.zip # a real deal shapefile
```

Writes `demo_planview.png` (plan view: parcel, drillable window, laterals) and
prints the feasibility + per-well lengths.

## Layout

- `src/narvi/parcel.py` — shapefile/synthetic parcel → UTM 13N (m)
- `src/narvi/placement.py` — drillable window + lateral placement geometry
- `src/narvi/generate.py` — parcel + params → inventory wells + feasibility
- `src/narvi/records.py` — `InventoryWell` / `ScenarioParams` / `Feasibility`

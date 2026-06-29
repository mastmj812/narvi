# narvi

Inventory-planning engine + app for the Permian: generate U-turn / single-lateral
well-inventory scenarios from a deal parcel, source landing TVD and the survey-grid
azimuth from the warehouse, persist scenarios, and hand the inventory off to the
forecasters (anduin type curves / erebor Novi-intel). narvi does **not** forecast —
it produces locations + configuration. Economics is out of scope (handed downstream).

## Layout

```
src/narvi/        the engine (pure-geometry core + DB layers), pip-installable
  records.py      data contract (ScenarioParams, InventoryWell, Zone, ...)
  parcel.py       parcel ingest (.zip / synthetic / GeoJSON) + UTM 13N work CRS
  placement.py    drillable window, rotated-lateral placement, azimuth
  generate.py     generate_scenario / generate_wine_rack
  warehouse.py    landing-TVD sourcing + offset-well grid azimuth (reads oilgas)
  persist.py      scenario persistence (narvi schema: scenario + inventory_well)
  viz.py          shared map GeoJSON + gun-barrel data + matplotlib renderers
sql/01_scenario.sql   narvi-schema DDL
backend/          FastAPI service wrapping the engine (app/api/*)
demo.py           CLI: generate + render PNGs / GeoJSON
tests/            engine tests;  backend/tests/   API tests
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .            # the narvi engine
.\.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" python-multipart httpx
```

Create `.env` (gitignored) with the warehouse `DB_*` keys (host/port/name/user/password/sslmode).

## Run

```powershell
.\start.ps1            # backend on :8078 + frontend on :5176
```

Or run the two processes manually (note the `--reload-dir ..\src` — without it,
uvicorn's reloader watches only `backend/` and will NOT pick up edits to the
`src/narvi` engine):

```powershell
# backend
cd backend; ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8078 --reload --reload-dir . --reload-dir ..\src
# frontend (separate window)
cd frontend; npm run dev
```

API docs at `http://127.0.0.1:8078/docs`. Key endpoints (all under `/api`):
`POST /parcels/upload`, `POST /generate`, `POST /warehouse/zones`,
`POST /warehouse/azimuth`, `GET|POST /scenarios`, `GET|DELETE /scenarios/{deal}/{id}`.

## Demo (CLI)

```powershell
.\.venv\Scripts\python.exe demo.py                       # synthetic 1-mile section
.\.venv\Scripts\python.exe demo.py deals.zip "hecker" winerack warehouse geojson
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q                  # engine + backend (20 tests)
```

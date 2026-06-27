-- Narvi scenario persistence (Phase 4, §7).
--
-- Scenarios are app WRITE-BACK data — generated inventory, not part of the
-- curated ETL refresh chain — so they live in their own `narvi` schema in the
-- oilgas warehouse. DDL is owned by the narvi repo (the warehouse ETL repo stays
-- decoupled from app tables). Idempotent: safe to re-run.
--
-- Geometry is stored in WGS84 (SRID 4326) for the map; a `detail` jsonb on each
-- well round-trips the full InventoryWell record (work-CRS coords, gunbarrel
-- offset, turn params) so a saved scenario reloads exactly as generated.

CREATE SCHEMA IF NOT EXISTS narvi;
COMMENT ON SCHEMA narvi IS
'Narvi inventory-planning scenarios (app write-back; NOT part of curated.refresh_all()).';

-- -----------------------------------------------------------------------------
-- scenario — one generation run (params + AOI + rollup). Keyed (deal_id, scenario_id).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narvi.scenario (
    deal_id                  TEXT NOT NULL,
    scenario_id              TEXT NOT NULL,
    name                     TEXT,
    well_type                TEXT NOT NULL,             -- 'single' | 'uturn'
    objective                TEXT NOT NULL,             -- 'max_lateral' | 'max_count'
    spacing_ft               DOUBLE PRECISION,
    setback_ft               DOUBLE PRECISION,
    setback_ns_ft            DOUBLE PRECISION,
    setback_ew_ft            DOUBLE PRECISION,
    azimuth_deg              DOUBLE PRECISION,           -- resolved azimuth actually used
    min_lateral_ft           DOUBLE PRECISION,
    uturn_min_leg_to_leg_ft  DOUBLE PRECISION,
    total_wells              INTEGER,
    total_legs               INTEGER,
    total_completed_ft       DOUBLE PRECISION,
    total_drilled_ft         DOUBLE PRECISION,
    params                   JSONB,                      -- full ScenarioParams
    summary                  JSONB,                      -- feasibility / wine-rack report
    aoi_geom                 geometry(Geometry, 4326),   -- parcel (Polygon or MultiPolygon)
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (deal_id, scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_narvi_scenario_aoi ON narvi.scenario USING GIST (aoi_geom);

-- -----------------------------------------------------------------------------
-- inventory_well — one generated well (1 leg single / 2 legs + turn U-turn).
-- Producing legs and the non-producing turn arc are separate geometries so a map
-- can style them differently; `detail` carries the exact InventoryWell for reload.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narvi.inventory_well (
    well_uid                    BIGSERIAL PRIMARY KEY,
    deal_id                     TEXT NOT NULL,
    scenario_id                 TEXT NOT NULL,
    well_name                   TEXT NOT NULL,
    well_type                   TEXT NOT NULL,
    formation                   TEXT,                    -- formation_blueox code
    target_tvd_ft               DOUBLE PRECISION,
    lateral_azimuth_deg         DOUBLE PRECISION,
    n_legs                      INTEGER NOT NULL,
    completed_lateral_ft        DOUBLE PRECISION,        -- EUR driver (sum of legs)
    drilled_lateral_ft          DOUBLE PRECISION,        -- D&C driver (legs + turn arc)
    nearest_neighbor_spacing_ft DOUBLE PRECISION,
    setback_ft                  DOUBLE PRECISION,
    turn_radius_ft              DOUBLE PRECISION,         -- NULL for single
    turn_dls_deg_per_100ft      DOUBLE PRECISION,
    turn_arc_ft                 DOUBLE PRECISION,
    legs_geom                   geometry(MultiLineString, 4326),  -- producing legs
    turn_geom                   geometry(LineString, 4326),       -- non-producing arc (nullable)
    detail                      JSONB NOT NULL,          -- full InventoryWell for exact reload
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (deal_id, scenario_id, well_name),
    FOREIGN KEY (deal_id, scenario_id)
        REFERENCES narvi.scenario (deal_id, scenario_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_narvi_inv_well_scenario
    ON narvi.inventory_well (deal_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_narvi_inv_well_legs
    ON narvi.inventory_well USING GIST (legs_geom);
CREATE INDEX IF NOT EXISTS idx_narvi_inv_well_formation
    ON narvi.inventory_well (formation);

-- -----------------------------------------------------------------------------
-- well_forecast — a production forecast + EUR per planned well, per SOURCE.
-- Keyed (deal, scenario, well_name, source) so the Novi-intel ML forecast and
-- the narvi analog type curve coexist for side-by-side comparison before one is
-- chosen for valuation. The monthly stream lives in `series` jsonb (the app
-- charts it); EURs are columns for cheap rollups.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narvi.well_forecast (
    forecast_uid    BIGSERIAL PRIMARY KEY,
    deal_id         TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    well_name       TEXT NOT NULL,
    source          TEXT NOT NULL,           -- 'novi_intel' | 'narvi_analog'
    eur_oil_bbl     DOUBLE PRECISION,
    eur_gas_mcf     DOUBLE PRECISION,
    eur_water_bbl   DOUBLE PRECISION,
    eur_ngl_bbl     DOUBLE PRECISION,
    eur_boe         DOUBLE PRECISION,
    horizon_months  INTEGER,
    series          JSONB,                   -- {months:[], oil:[], gas:[], water:[]}
    match           JSONB,                   -- provenance / match quality
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (deal_id, scenario_id, well_name, source),
    FOREIGN KEY (deal_id, scenario_id)
        REFERENCES narvi.scenario (deal_id, scenario_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_narvi_well_forecast_scenario
    ON narvi.well_forecast (deal_id, scenario_id, source);

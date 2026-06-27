"""Backend smoke tests via FastAPI TestClient. The /generate path is pure
geometry (no DB); warehouse/scenarios endpoints need the live warehouse and are
covered by the narvi library tests + manual checks."""

from shapely.geometry import mapping

from fastapi.testclient import TestClient
from narvi import synthetic_section
from narvi.viz import _to_wgs_geom

from app.main import app

client = TestClient(app)


def _synthetic_parcel_geojson():
    return mapping(_to_wgs_geom(synthetic_section()))


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_generate_single_returns_geojson_and_gunbarrel():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 200, "formation": "WCA_1",
                   "target_tvd_ft": 11500, "azimuth_deg": 0.0},
        "mode": "single",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["placed_wells"] == 5 and d["placed_legs"] == 5
    kinds = [f["properties"]["kind"] for f in d["geojson"]["features"]]
    assert kinds.count("leg") == 5 and kinds.count("parcel") == 1
    assert len(d["gunbarrel"]["points"]) == 5


def test_generate_uturn_has_turns():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 990, "setback_ft": 200, "formation": "WCA_1",
                   "target_tvd_ft": 11500, "azimuth_deg": 0.0, "well_type": "uturn"},
        "mode": "single",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200
    d = r.json()
    turns = [f for f in d["geojson"]["features"] if f["properties"]["kind"] == "turn"]
    assert len(turns) == 2


def test_generate_winerack_requires_zones():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 200},
        "mode": "winerack",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 400  # no zones and no source_tvd

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import (
    ScenarioParams,
    Zone,
    generate_scenario,
    generate_wine_rack,
    gunbarrel_data,
    scenario_geojson,
    synthetic_section,
)


def _params(**kw):
    base = dict(formation="WCA_1", target_tvd_ft=11500, azimuth_deg=0.0,
                spacing_ft=880, setback_ft=200, min_lateral_ft=4000)
    base.update(kw)
    return ScenarioParams(**base)


def test_scenario_geojson_structure_and_counts():
    parcel = synthetic_section()
    wells, window, _ = generate_scenario(parcel, _params())  # 5 single laterals
    fc = scenario_geojson(parcel, window, wells)

    assert fc["type"] == "FeatureCollection"
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert kinds.count("parcel") == 1
    assert kinds.count("window") == 1
    assert kinds.count("leg") == 5      # one LineString per producing leg
    assert kinds.count("turn") == 0     # singles have no turn
    # the whole thing must be JSON-serializable for a front end
    json.dumps(fc)


def test_scenario_geojson_legs_are_wgs84_lonlat():
    parcel = synthetic_section()  # default center (-103.8, 31.9)
    wells, window, _ = generate_scenario(parcel, _params())
    fc = scenario_geojson(parcel, window, wells)
    leg = next(f for f in fc["features"] if f["properties"]["kind"] == "leg")
    (lon, lat), _ = leg["geometry"]["coordinates"]
    assert -104.5 < lon < -103.0 and 31.0 < lat < 32.5
    assert leg["properties"]["formation"] == "WCA_1"
    assert "gunbarrel_x_ft" in leg["properties"]


def test_uturn_geojson_has_turn_features():
    parcel = synthetic_section()
    wells, window, _ = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=990))
    fc = scenario_geojson(parcel, window, wells)
    turns = [f for f in fc["features"] if f["properties"]["kind"] == "turn"]
    assert len(turns) == 2  # 5 legs -> 2 U-turns + 1 single
    t = turns[0]
    assert t["geometry"]["type"] == "LineString"
    assert t["properties"]["radius_ft"] == 495
    assert len(t["geometry"]["coordinates"]) >= 3  # arc polyline


def test_gunbarrel_data_points_links_and_legend():
    parcel = synthetic_section()
    base = _params(well_type="single")
    zones = [Zone("WCA_1", 11500), Zone("WCA_2", 11700)]
    wells, _, _ = generate_wine_rack(parcel, base, zones)
    data = gunbarrel_data(wells)

    # one point per producing leg; legend shallow -> deep
    assert len(data["points"]) == sum(len(w.legs) for w in wells)
    assert [f["formation"] for f in data["formations"]] == ["WCA_1", "WCA_2"]
    assert data["formations"][0]["color"] != data["formations"][1]["color"]
    # singles -> no U-turn links
    assert data["links"] == []
    pt = data["points"][0]
    assert {"well_name", "formation", "color", "offset_ft", "tvd_ft", "well_type"} <= pt.keys()


def test_gunbarrel_links_for_uturns():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=990))
    data = gunbarrel_data(wells)
    assert len(data["links"]) == 2  # two U-turns linked at their TVD
    lk = data["links"][0]
    assert lk["offset_a_ft"] != lk["offset_b_ft"] and lk["tvd_ft"] == 11500

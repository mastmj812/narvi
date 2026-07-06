"""DB-free tests for warehouse.py's pure parts: unit-membership vs context
classification and stable pass-through naming (culls key on well_name, so names
must survive a re-fetch byte-for-byte)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shapely.geometry import box

from narvi.records import FT_PER_M, InventoryWell, Leg
from narvi.warehouse import _classify_membership, _passthrough_well


def _leg_well(name, category, heel_xy, toe_xy):
    leg = Leg(heel_xy=heel_xy, toe_xy=toe_xy, heel_lonlat=(0, 0), toe_lonlat=(0, 0),
              length_ft=0.0, gunbarrel_x_ft=0.0)
    w = InventoryWell(
        scenario_id="", deal_id="", well_name=name, well_type="single",
        formation="WCA_1", target_tvd_ft=11500.0, lateral_azimuth_deg=0.0,
        legs=[leg], turn=None, completed_lateral_ft=0.0, drilled_lateral_ft=0.0,
        nearest_neighbor_spacing_ft=0.0, setback_ft=0.0, category=category)
    mid = ((heel_xy[0] + toe_xy[0]) / 2.0, (heel_xy[1] + toe_xy[1]) / 2.0)
    return (w, mid)


def test_classify_membership_and_context():
    parcel = box(0.0, 0.0, 1600.0, 1600.0)          # ~1 mile square, work-CRS m
    inside = _leg_well("in", "pdp", (100.0, 800.0), (1500.0, 800.0))
    edge_clip = _leg_well("clip", "pdp", (-2000.0, 100.0), (200.0, 100.0))   # ~9% inside
    near = _leg_well("near", "pdp", (2000.0, 0.0), (2000.0, 1600.0))         # 400 m off
    far = _leg_well("far", "pdp", (20000.0, 0.0), (20000.0, 1600.0))
    near_pud = _leg_well("pud", "pud", (2100.0, 0.0), (2100.0, 1600.0))      # PUD: no context

    items = [inside, edge_clip, near, far, near_pud]
    kept, context = _classify_membership(items, parcel, 0.30, 5280.0 / FT_PER_M)
    assert [w.well_name for w, _ in kept] == ["in"]
    # edge_clip fails membership but is close -> context; PUD never context
    assert sorted(w.well_name for w, _ in context) == ["clip", "near"]

    # no radius -> no context wells at all
    kept2, context2 = _classify_membership(items, parcel, 0.30, None)
    assert [w.well_name for w, _ in kept2] == ["in"] and context2 == []


def test_passthrough_name_stability():
    # api10 present -> the name IS the api10; absent -> the caller's stable
    # fallback (warehouse-key derived), never a list position.
    w1, _ = _passthrough_well("WCA_1", 11500, "4230112345", None, "pdp",
                              -103.8, 31.9, -103.8, 31.92, 0.0, fallback_name="x")
    assert w1.well_name == "4230112345"
    w2, _ = _passthrough_well("WCA_1", 11500, None, None, "pud",
                              -103.8, 31.9, -103.8, 31.92, 0.0, fallback_name="pud-991")
    assert w2.well_name == "pud-991"

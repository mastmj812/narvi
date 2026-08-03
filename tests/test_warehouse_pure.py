"""DB-free tests for warehouse.py's pure parts: unit-membership vs context
classification and stable pass-through naming (culls key on well_name, so names
must survive a re-fetch byte-for-byte)."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shapely.geometry import box

from narvi.records import FT_PER_M, InventoryWell, Leg
from narvi.warehouse import (
    AzimuthStats,
    _classify_membership,
    _passthrough_well,
    axial_mean_deg,
    resolve_baseline_azimuth,
    sticks_azimuth_deg,
)


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
                              -103.8, 31.9, -103.8, 31.92, fallback_name="x")
    assert w1.well_name == "4230112345"
    w2, _ = _passthrough_well("WCA_1", 11500, None, None, "pud",
                              -103.8, 31.9, -103.8, 31.92, fallback_name="pud-991")
    assert w2.well_name == "pud-991"


# ---------------------------------------------------------------------------
# Baseline frame azimuth (the toucan defect, 2026-08-03): adopted inventory
# must derive its cross-section azimuth from its OWN sticks — an unconfident
# neighborhood circular mean (bimodal offset grids) is never usable.
# ---------------------------------------------------------------------------


def _bearing_well(name, bearing_deg, length_m=3000.0, heel=(0.0, 0.0),
                  category="pud"):
    """Single-leg well at a compass bearing in the work CRS."""
    b = math.radians(bearing_deg)
    toe = (heel[0] + length_m * math.sin(b), heel[1] + length_m * math.cos(b))
    return _leg_well(name, category, heel, toe)[0]


def test_axial_mean_coherent_and_folded():
    # 56/58 with a REVERSED 237 (same axis as 57): axial mean folds it in
    az, r = axial_mean_deg([56.0, 58.0, 237.0])
    assert abs(az - 57.0) < 0.1 and r > 0.99
    assert axial_mean_deg([]) == (None, 0.0)


def test_axial_mean_bimodal_low_coherence():
    # The toucan neighborhood signature: a ~57 deg grid cluster mixed with a
    # ~0/175 deg N-S cluster -> low R, mean stranded between the modes.
    bearings = [57.0] * 6 + [0.5, 179.5, 175.0, 2.0]
    az, r = axial_mean_deg(bearings)
    assert r < 0.85                       # below the trust floor
    assert 10.0 < az < 50.0               # a direction nothing drills


def test_sticks_azimuth_own_geometry():
    wells = [_bearing_well("a", 57.0), _bearing_well("b", 237.0)]  # same axis
    az = sticks_azimuth_deg(wells)
    assert az is not None and abs(az - 57.0) < 0.1
    # zero-length legs skipped; nothing qualifying -> None
    degenerate = _leg_well("z", "pdp", (0.0, 0.0), (0.0, 0.0))[0]
    assert sticks_azimuth_deg([degenerate]) is None
    assert sticks_azimuth_deg([]) is None


def test_sticks_azimuth_mixed_unit_dominant_mode():
    # The eqv expedition/harrisonwc shape: a ~53 deg majority mixed with a
    # ~170 deg N-S minority IN the unit. A plain axial mean strands between
    # the modes (~43 deg — nothing drills that); the trimmed estimator must
    # converge on the majority family.
    wells = ([_bearing_well(f"m{i}", 53.0 + (i % 5)) for i in range(20)]
             + [_bearing_well(f"n{i}", 170.0 + (i % 3)) for i in range(9)])
    plain, r = axial_mean_deg([53.0 + (i % 5) for i in range(20)]
                              + [170.0 + (i % 3) for i in range(9)])
    assert r < 0.85 and _dist(plain, 55.0) > 5.0   # the mean DOES strand
    az = sticks_azimuth_deg(wells)
    assert az is not None and _dist(az, 55.0) < 3.0


def _dist(a, b):
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)


def _stats(az, confident):
    return AzimuthStats(wells=40, azimuth_deg=az, coherence=0.62,
                        circ_std_deg=None, confident=confident)


def test_resolve_baseline_azimuth_trust_order():
    parcel = box(0.0, 0.0, 4000.0, 800.0)    # long axis E-W -> bearing 90
    kept = [_bearing_well("a", 56.8), _bearing_well("b", 57.2)]

    # 1. kept sticks win — even against a (wrong, unconfident) neighborhood
    #    mean: the toucan reproduction (stored 41.2 vs true ~57).
    assert resolve_baseline_azimuth(kept, _stats(41.2, False), parcel) == 57.0
    # ... and even against a CONFIDENT one: own geometry is still truer.
    assert resolve_baseline_azimuth(kept, _stats(41.2, True), parcel) == 57.0

    # 2. empty unit: a confident neighborhood grid is used ...
    assert resolve_baseline_azimuth([], _stats(162.5, True), parcel) == 162.5
    # 3. ... an unconfident one is NOT — parcel long axis instead.
    assert resolve_baseline_azimuth([], _stats(41.2, False), parcel) == 90.0
    assert resolve_baseline_azimuth([], None, parcel) == 90.0

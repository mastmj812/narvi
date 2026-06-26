import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import ScenarioParams, generate_scenario, synthetic_section


def _params(**kw):
    base = dict(formation="WCA_1", target_tvd_ft=11500, azimuth_deg=0.0,
                spacing_ft=880, setback_ft=200, min_lateral_ft=4000)
    base.update(kw)
    return ScenarioParams(**base)


def test_section_single_laterals_count_and_length():
    parcel = synthetic_section()  # 5,280 ft square, 640 ac
    wells, _, feas = generate_scenario(parcel, _params())
    assert feas.placed == 5 and feas.legs == 5
    # 5280 - 2*200 setback = 4880 ft drillable height
    for w in wells:
        assert w.well_type == "single" and len(w.legs) == 1 and w.turn is None
        assert abs(w.completed_lateral_ft - 4880) < 5
        assert w.drilled_lateral_ft == w.completed_lateral_ft  # single == completed


def test_centered_symmetric_spacing():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params())
    xs = sorted(w.legs[0].gunbarrel_x_ft for w in wells)
    for got, want in zip(xs, [-1760, -880, 0, 880, 1760]):
        assert abs(got - want) < 1


def test_square_section_azimuth_invariant():
    parcel = synthetic_section()
    n0 = generate_scenario(parcel, _params(azimuth_deg=0))[2].placed
    n90 = generate_scenario(parcel, _params(azimuth_deg=90))[2].placed
    assert n0 == n90 == 5  # a square section is symmetric under a 90° rotation


def test_min_length_filters_short_laterals():
    parcel = synthetic_section()
    # a 6,000 ft minimum can't be met in a 4,880 ft window -> zero placed
    wells, _, feas = generate_scenario(parcel, _params(min_lateral_ft=6000))
    assert feas.placed == 0


def test_uturn_pairs_legs_with_turn():
    parcel = synthetic_section()
    wells, _, feas = generate_scenario(parcel, _params(well_type="uturn"))
    uturns = [w for w in wells if w.well_type == "uturn"]
    singles = [w for w in wells if w.well_type == "single"]
    # 5 legs -> 2 U-turns (4 legs) + 1 single leftover
    assert len(uturns) == 2 and len(singles) == 1
    assert feas.legs == 5
    for w in uturns:
        assert len(w.legs) == 2 and w.turn is not None
        # legs trimmed by R = spacing/2 = 440 ft from the 4,880 ft span
        for leg in w.legs:
            assert abs(leg.length_ft - 4440) < 10
        assert w.turn.radius_ft == 440                          # spacing / 2
        assert abs(w.turn.dls_deg_per_100ft - 13.02) < 0.1      # 5729.58 / 440
        # turn arc is non-producing: drilled = completed + pi*R
        assert w.drilled_lateral_ft > w.completed_lateral_ft
        assert abs((w.drilled_lateral_ft - w.completed_lateral_ft) - math.pi * 440) < 5

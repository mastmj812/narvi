import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import (
    ScenarioParams,
    Zone,
    generate_scenario,
    generate_wine_rack,
    synthetic_section,
)


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
    # 990 ft leg-to-leg = the floor (valid); R = 495 ft
    wells, _, feas = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=990))
    uturns = [w for w in wells if w.well_type == "uturn"]
    singles = [w for w in wells if w.well_type == "single"]
    # 5 legs -> 2 U-turns (4 legs) + 1 single leftover
    assert len(uturns) == 2 and len(singles) == 1
    assert feas.legs == 5
    for w in uturns:
        assert len(w.legs) == 2 and w.turn is not None
        # legs trimmed by R = spacing/2 = 495 ft from the 4,880 ft span
        for leg in w.legs:
            assert abs(leg.length_ft - 4385) < 10
        assert w.turn.radius_ft == 495                          # spacing / 2
        assert abs(w.turn.dls_deg_per_100ft - 11.58) < 0.1      # 5729.58 / 495
        # turn arc is non-producing: drilled = completed + pi*R
        assert w.drilled_lateral_ft > w.completed_lateral_ft
        assert abs((w.drilled_lateral_ft - w.completed_lateral_ft) - math.pi * 495) < 5


def test_uturn_below_floor_falls_back_to_singles():
    parcel = synthetic_section()
    # 880 ft leg-to-leg is below the 990 ft floor -> undrillable turn -> singles
    wells, _, feas = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=880))
    assert wells and all(w.well_type == "single" for w in wells)
    assert "floor" in feas.note


def test_wine_rack_stagger_and_interzone_offset():
    parcel = synthetic_section()
    base = _params(well_type="single")  # 880 ft spacing -> stagger 440
    zones = [Zone("WCA_1", 11500), Zone("WCA_2", 11700)]  # dTVD 200
    wells, _, rep = generate_wine_rack(parcel, base, zones)

    assert len(rep.zones) == 2
    assert rep.stagger_ft == 440  # spacing / 2
    z_shallow = next(z for z in rep.zones if z.target_tvd_ft == 11500)
    z_deep = next(z for z in rep.zones if z.target_tvd_ft == 11700)
    assert z_shallow.stagger_offset_ft == 0
    assert z_deep.stagger_offset_ft == 440
    # wine-rack diagonal = sqrt(stagger^2 + dTVD^2) = sqrt(440^2 + 200^2)
    assert abs(rep.min_interzone_offset_ft - math.hypot(440, 200)) < 1
    assert rep.min_interzone_offset_ok  # 483 ft >= 300 ft min
    # the deep zone's legs sit 440 ft off the shallow zone's (mod spacing)
    deep_x = {round(leg.gunbarrel_x_ft) for w in wells if w.target_tvd_ft == 11700 for leg in w.legs}
    assert all(abs((x % 880) - 440) < 1 for x in deep_x)


def test_asymmetric_setback_shortens_ns_laterals():
    parcel = synthetic_section()  # axis-aligned 5,280 ft square
    # az=0 -> N-S laterals; the N/S setback controls their length
    uni, _, _ = generate_scenario(parcel, _params())  # uniform 200
    asy, _, _ = generate_scenario(parcel, _params(setback_ns_ft=600, setback_ew_ft=200))
    assert abs(uni[0].legs[0].length_ft - 4880) < 10   # 5280 - 2*200
    assert abs(asy[0].legs[0].length_ft - 4080) < 30   # 5280 - 2*600 (N/S setback)


def _rect_parcel(w_ft, h_ft):
    from shapely.affinity import scale
    sq = synthetic_section(5280.0)
    return scale(sq, xfact=w_ft / 5280.0, yfact=h_ft / 5280.0, origin=sq.centroid)


def test_objective_max_count_vs_max_lateral():
    parcel = _rect_parcel(10560, 5280)  # 2 mi (E-W) x 1 mi (N-S)
    base = dict(formation="X", target_tvd_ft=1.0, spacing_ft=880, setback_ft=200, min_lateral_ft=4000)
    lat_w, _, lat_f = generate_scenario(parcel, ScenarioParams(objective="max_lateral", **base))
    cnt_w, _, cnt_f = generate_scenario(parcel, ScenarioParams(objective="max_count", **base))
    # max_count fits more (shorter) laterals; max_lateral runs the long axis -> longer
    assert cnt_f.legs > lat_f.legs
    avg_lat = sum(w.legs[0].length_ft for w in lat_w) / len(lat_w)
    avg_cnt = sum(w.legs[0].length_ft for w in cnt_w) / len(cnt_w)
    assert avg_lat > avg_cnt

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
                spacing_ft=880, setback_ft=200, min_lateral_ft=4000, anchor="center")
    base.update(kw)
    return ScenarioParams(**base)


def test_section_single_laterals_count_and_length():
    parcel = synthetic_section()  # 5,280 ft square, 640 ac
    wells, _, feas = generate_scenario(parcel, _params())
    # center max-packs: the half-spacing-shifted (still centered) phase fits 6 at
    # 880 ft in the 4,880 ft window — one more than a row on the exact midline
    assert feas.placed == 6 and feas.legs == 6
    # 5280 - 2*200 setback = 4880 ft drillable height
    for w in wells:
        assert w.well_type == "single" and len(w.legs) == 1 and w.turn is None
        assert abs(w.completed_lateral_ft - 4880) < 5
        assert w.drilled_lateral_ft == w.completed_lateral_ft  # single == completed


def test_centered_symmetric_spacing():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params())
    xs = sorted(w.legs[0].gunbarrel_x_ft for w in wells)
    # 6 rows straddling the midline (max-pack), still symmetric about 0
    for got, want in zip(xs, [-2200, -1320, -440, 440, 1320, 2200]):
        assert abs(got - want) < 1


def test_square_section_azimuth_invariant():
    parcel = synthetic_section()
    n0 = generate_scenario(parcel, _params(azimuth_deg=0))[2].placed
    n90 = generate_scenario(parcel, _params(azimuth_deg=90))[2].placed
    assert n0 == n90 == 6  # a square section is symmetric under a 90° rotation


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


def test_uturn_dp_skip_beats_greedy():
    # Five legs (heels aligned), one short toe at the front: [2000, 6000, 6000,
    # 6000, 6000] ft. Greedy adjacent pairing forms (0,1) = short+full -> sub-min,
    # dropped, then (2,3) compliant, leaving leg 4 a (sub-min) single -> 1 U-turn.
    # The DP skips the short leg 0 and pairs (1,2)+(3,4) -> 2 compliant U-turns.
    from shapely.geometry import Point

    from narvi.generate import _place_uturns
    from narvi.records import FT_PER_M

    p = _params(well_type="uturn", spacing_ft=990, min_lateral_ft=7000)
    spacing_m = 990 / FT_PER_M
    legs = [(i * spacing_m, 0.0, ft / FT_PER_M)
            for i, ft in enumerate([2000, 6000, 6000, 6000, 6000])]
    wells = _place_uturns(legs, spacing_m, Point(0.0, 0.0), 0.0, (0.0, (0.0, 0.0)), p, True)
    kept_uturns = [w for w in wells
                   if w.well_type == "uturn" and w.completed_lateral_ft >= p.min_lateral_ft]
    assert len(kept_uturns) == 2                       # greedy would yield only 1
    # the dropped short leg survives as a sub-minimum single (filtered downstream)
    assert any(w.well_type == "single" and w.completed_lateral_ft < p.min_lateral_ft
               for w in wells)


def test_uturn_dp_matches_greedy_on_uniform_unit():
    # On a regular section every pairing is compliant and equal, so the DP must
    # reproduce the greedy layout: 2 U-turns + one trailing leftover single.
    parcel = synthetic_section()
    wells, _, feas = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=990))
    assert len([w for w in wells if w.well_type == "uturn"]) == 2
    assert len([w for w in wells if w.well_type == "single"]) == 1
    assert feas.legs == 5


def test_parcel_from_geojson_repairs_invalid_polygon():
    # A self-intersecting "bowtie" boundary (a common uploaded-shapefile defect)
    # must be repaired on ingest, not crash setback/clip ops or leak a lateral out.
    from narvi.parcel import parcel_from_geojson

    bowtie = {"type": "Polygon", "coordinates": [[
        [-103.80, 31.90], [-103.79, 31.91], [-103.79, 31.90], [-103.80, 31.91],
        [-103.80, 31.90]]]}
    g = parcel_from_geojson(bowtie)
    assert g.is_valid and g.area > 0
    # and it generates without escaping its own boundary
    wells, _, _ = generate_scenario(
        g, _params(azimuth_deg=None, anchor="east", setback_ft=200, min_lateral_ft=1500))
    from shapely.geometry import Point
    ref = g.buffer(1.0)
    for w in wells:
        for leg in w.legs:
            mid = Point((leg.heel_xy[0] + leg.toe_xy[0]) / 2, (leg.heel_xy[1] + leg.toe_xy[1]) / 2)
            assert ref.contains(mid)


def test_west_anchor_azimuth_from_lease_line_keeps_laterals_parallel():
    # A parcel tilted 12 deg: the user anchors off the west line, so the azimuth must
    # come from THAT lease line (not the bbox long axis / a sourced grid), making the
    # laterals exactly parallel to the setback regardless of any azimuth hint passed.
    import math

    from shapely.affinity import rotate as _rot

    from narvi.placement import anchor_edge_azimuth

    parcel = _rot(synthetic_section(5280.0), 12.0, origin="centroid")
    west_az = anchor_edge_azimuth(parcel, "west")
    # a deliberately wrong azimuth hint is overridden by the anchor line
    wells, _, _ = generate_scenario(
        parcel, _params(azimuth_deg=90.0, anchor="west", setback_ft=200, min_lateral_ft=3000))
    assert wells
    assert abs(wells[0].lateral_azimuth_deg - round(west_az, 1)) < 0.1
    for w in wells:
        for leg in w.legs:
            b = math.degrees(math.atan2(leg.toe_xy[0] - leg.heel_xy[0],
                                        leg.toe_xy[1] - leg.heel_xy[1])) % 180.0
            assert abs(b - west_az) < 0.05      # laterals parallel to the lease line


def test_west_anchor_first_lateral_flush_on_setback_line():
    # A parcel whose west edge runs ~1 deg off the lateral azimuth: a constant-cross-
    # section row grazes the SW corner as a degenerate point, so anchoring at the
    # bbox corner would push the first real lateral a whole spacing inside the setback
    # line. The flush anchor must place the westmost leg ~on the E/W setback (200 ft).
    from shapely.affinity import rotate as _rot

    parcel = _rot(synthetic_section(5280.0), 1.0, origin="centroid")  # tilt 1 deg
    az = 1.0  # laterals along the (tilted) grid -> west edge ~parallel to them
    wells, _, _ = generate_scenario(
        parcel, _params(azimuth_deg=az, setback_ft=200, anchor="west", min_lateral_ft=3000))
    # west boundary of the drillable window, in the work CRS
    from narvi.placement import drillable_window
    win = drillable_window(parcel, 200.0)
    minx_e = win.bounds[0]
    westmost = min(min(leg.heel_xy[0], leg.toe_xy[0]) for w in wells for leg in w.legs)
    # the westmost leg sits flush ON the window's west edge (sub-foot after the flush
    # bisection), not a full spacing inside it (old bbox-corner anchor left ~880 ft)
    from narvi.records import FT_PER_M
    assert abs(westmost - minx_e) * FT_PER_M < 5


def test_wine_rack_stagger_and_interzone_offset():
    # West anchor preserves the alternating stagger (a center anchor now max-packs
    # each bench, which can converge them to the same cross-section instead).
    parcel = synthetic_section()
    base = _params(well_type="single", anchor="west")  # 880 ft spacing -> stagger 440
    zones = [Zone("WCA_1", 11500), Zone("WCA_2", 11700)]  # dTVD 200
    wells, _, rep = generate_wine_rack(parcel, base, zones)

    assert len(rep.zones) == 2
    assert rep.stagger_ft == 440  # spacing / 2
    z_shallow = next(z for z in rep.zones if z.target_tvd_ft == 11500)
    z_deep = next(z for z in rep.zones if z.target_tvd_ft == 11700)
    assert z_shallow.stagger_offset_ft == 0
    assert z_deep.stagger_offset_ft == 440
    # actual nearest-leg 3-D gap between the staggered zones = sqrt(440^2 + 200^2)
    assert abs(rep.min_interzone_offset_ft - math.hypot(440, 200)) < 1
    assert rep.min_interzone_offset_ok  # 483 ft >= 300 ft min
    # the deep zone's legs sit 440 ft off the shallow zone's (mod spacing)
    sh_x = sorted({round(leg.gunbarrel_x_ft) for w in wells if w.target_tvd_ft == 11500 for leg in w.legs})
    dp_x = sorted({round(leg.gunbarrel_x_ft) for w in wells if w.target_tvd_ft == 11700 for leg in w.legs})
    assert all(any(abs((d - s) % 880 - 440) < 1 for s in sh_x) for d in dp_x)


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

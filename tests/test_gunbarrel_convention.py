"""Pins for THE canonical gun-barrel convention (placement.cross_axis /
gunbarrel_offset_ft), sign rule v2: +offset points into the NE half — East for
N-S laterals, North for E-W, SE at the 45° seam — origin = the parcel centroid. Both the
generator and the warehouse pass-through project through the same formula, so
these signs are what keeps curate / override / context overlays aligned."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import ScenarioParams, generate_scenario, synthetic_section
from narvi.placement import cross_axis, gunbarrel_offset_ft, plus_offset_bearing_deg
from narvi.records import FT_PER_M


def _params(**kw):
    base = dict(formation="WCA_1", target_tvd_ft=11500, azimuth_deg=0.0,
                spacing_ft=880, setback_ft=200, min_lateral_ft=4000, anchor="center")
    base.update(kw)
    return ScenarioParams(**base)


def test_cross_axis_sign_convention():
    # N-S laterals (az=0): +offset points compass East
    ex, ny = cross_axis(0.0)
    assert abs(ex - 1.0) < 1e-9 and abs(ny) < 1e-9
    # E-W laterals (az=90): +offset points compass North
    ex, ny = cross_axis(90.0)
    assert abs(ex) < 1e-9 and abs(ny - 1.0) < 1e-9


# THE golden table (lateral azimuth -> compass bearing of +offset). Byte-identical
# copies pin the same rule in anduin (exports/blueox.py), erebor (_canonical_axis)
# and engineering_db (dealintake/geo.py) — change every copy or none.
GOLDEN_PLUS_BEARING = [
    (0.0, 90.0), (0.3, 90.3), (40.2, 130.2), (45.0, 135.0), (45.04, 135.04),
    (45.06, 315.06), (45.1, 315.1), (55.3, 325.3), (71.3, 341.3), (89.0, 359.0),
    (90.0, 0.0), (128.8, 38.8), (161.3, 71.3), (179.5, 89.5), (179.96, 89.96),
    (180.0, 90.0), (200.0, 110.0), (-18.7, 71.3),
]


def test_plus_offset_bearing_golden_table():
    for az, want in GOLDEN_PLUS_BEARING:
        got = plus_offset_bearing_deg(az)
        assert abs((got - want + 180.0) % 360.0 - 180.0) < 1e-6, (az, got, want)
        ex, ny = cross_axis(az)
        b = math.radians(want)
        assert abs(ex - math.sin(b)) < 1e-9 and abs(ny - math.cos(b)) < 1e-9, az


def test_plus_points_into_ne_half():
    # W -> E for N-S-ish, S -> N for E-W-ish: + never has a negative NE component
    for tenth in range(0, 1800):
        ex, ny = cross_axis(tenth / 10.0)
        assert ex + ny > -1e-9, tenth / 10.0


def test_no_seam_at_0_180():
    # a ~0° TRUE plan is ~179.5° GRID in narvi: both read W -> E (rule v1 flipped it)
    for a, b in ((0.1, 179.9), (0.3, 179.5), (1.0, 179.0)):
        assert cross_axis(a)[0] > 0.99 and cross_axis(b)[0] > 0.99


def test_cross_axis_axial_folding():
    # a lateral has no direction: az and az+180 are the same grid line
    assert cross_axis(20.0) == cross_axis(200.0)
    assert cross_axis(0.0) == cross_axis(180.0)


def test_gunbarrel_offset_formula():
    # 100 m east of the origin at az=0 -> +100 m in feet
    off = gunbarrel_offset_ft((100.0, 0.0), 0.0, (0.0, 0.0))
    assert abs(off - 100.0 * FT_PER_M) < 1e-6
    # 100 m north at az=90 -> positive (North is positive)
    off = gunbarrel_offset_ft((0.0, 100.0), 90.0, (0.0, 0.0))
    assert abs(off - 100.0 * FT_PER_M) < 1e-6


def test_generated_offsets_positive_east_at_az0():
    # az=0 (N-S laterals): the easternmost well must carry the max POSITIVE
    # offset, and every offset must equal the leg midpoint's easting delta from
    # the parcel centroid — the exact formula the warehouse pass-through uses.
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(azimuth_deg=0.0))
    cx = parcel.centroid.x
    for w in wells:
        leg = w.legs[0]
        mid_e = (leg.heel_xy[0] + leg.toe_xy[0]) / 2.0
        want = (mid_e - cx) * FT_PER_M
        assert abs(leg.gunbarrel_x_ft - want) < 1.0
    east = max(wells, key=lambda w: (w.legs[0].heel_xy[0] + w.legs[0].toe_xy[0]) / 2)
    assert east.legs[0].gunbarrel_x_ft > 0
    assert east.legs[0].gunbarrel_x_ft == max(w.legs[0].gunbarrel_x_ft for w in wells)


def test_generated_offsets_positive_north_at_az90():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(azimuth_deg=90.0))
    north = max(wells, key=lambda w: (w.legs[0].heel_xy[1] + w.legs[0].toe_xy[1]) / 2)
    assert north.legs[0].gunbarrel_x_ft > 0
    assert north.legs[0].gunbarrel_x_ft == max(w.legs[0].gunbarrel_x_ft for w in wells)


def test_generated_offsets_positive_east_at_grid_179_5():
    # Rally Caps 1-12: 0.3° TRUE = 179.5° GRID — the easternmost well is now +
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(azimuth_deg=179.5))
    east = max(wells, key=lambda w: (w.legs[0].heel_xy[0] + w.legs[0].toe_xy[0]) / 2)
    assert east.legs[0].gunbarrel_x_ft == max(w.legs[0].gunbarrel_x_ft for w in wells) > 0


def test_azimuth_fold_equivalence():
    # az=200 folds to az=20: identical layout, identical offset signs
    parcel = synthetic_section()
    w20, _, _ = generate_scenario(parcel, _params(azimuth_deg=20.0))
    w200, _, _ = generate_scenario(parcel, _params(azimuth_deg=200.0))
    x20 = sorted(w.legs[0].gunbarrel_x_ft for w in w20)
    x200 = sorted(w.legs[0].gunbarrel_x_ft for w in w200)
    assert len(x20) == len(x200)
    for a, b in zip(x20, x200):
        assert abs(a - b) < 1.0


def test_symmetric_section_offsets_centered_on_parcel_centroid():
    # the synthetic section is symmetric, so parcel-centroid offsets stay the
    # historical symmetric ladder (regression guard vs the old window-midline)
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params())
    xs = sorted(w.legs[0].gunbarrel_x_ft for w in wells)
    for got, want in zip(xs, [-2200, -1320, -440, 440, 1320, 2200]):
        assert abs(got - want) < 1


def test_uturn_offsets_use_same_frame():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(well_type="uturn", spacing_ft=990))
    cx = parcel.centroid.x
    for w in wells:
        for leg in w.legs:
            mid_e = (leg.heel_xy[0] + leg.toe_xy[0]) / 2.0
            assert abs(leg.gunbarrel_x_ft - (mid_e - cx) * FT_PER_M) < 1.0

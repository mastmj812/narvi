"""Pins for THE canonical gun-barrel convention (placement.cross_axis /
gunbarrel_offset_ft): +offset = right-hand side looking down the folded azimuth
(East for N-S laterals, South for E-W), origin = the parcel centroid. Both the
generator and the warehouse pass-through project through the same formula, so
these signs are what keeps curate / override / context overlays aligned."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import ScenarioParams, generate_scenario, synthetic_section
from narvi.placement import cross_axis, gunbarrel_offset_ft
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
    # E-W laterals (az=90): +offset points compass South
    ex, ny = cross_axis(90.0)
    assert abs(ex) < 1e-9 and abs(ny + 1.0) < 1e-9


def test_cross_axis_axial_folding():
    # a lateral has no direction: az and az+180 are the same grid line
    assert cross_axis(20.0) == cross_axis(200.0)
    assert cross_axis(0.0) == cross_axis(180.0)


def test_gunbarrel_offset_formula():
    # 100 m east of the origin at az=0 -> +100 m in feet
    off = gunbarrel_offset_ft((100.0, 0.0), 0.0, (0.0, 0.0))
    assert abs(off - 100.0 * FT_PER_M) < 1e-6
    # 100 m north at az=90 -> negative (South is positive)
    off = gunbarrel_offset_ft((0.0, 100.0), 90.0, (0.0, 0.0))
    assert abs(off + 100.0 * FT_PER_M) < 1e-6


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


def test_generated_offsets_positive_south_at_az90():
    parcel = synthetic_section()
    wells, _, _ = generate_scenario(parcel, _params(azimuth_deg=90.0))
    south = min(wells, key=lambda w: (w.legs[0].heel_xy[1] + w.legs[0].toe_xy[1]) / 2)
    assert south.legs[0].gunbarrel_x_ft > 0
    assert south.legs[0].gunbarrel_x_ft == max(w.legs[0].gunbarrel_x_ft for w in wells)


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

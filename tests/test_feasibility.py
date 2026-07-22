"""Parcel feasibility + config scan (Castaway half-section class of problems):
the app must SAY what a bearing can hold and rank workable configurations,
instead of returning silent zeros on parcels the defaults don't fit."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shapely.affinity import scale

from narvi import (
    ScenarioParams,
    Zone,
    generate_scenario,
    generate_wine_rack,
    parcel_feasibility,
    scan_configs,
    synthetic_section,
)
from narvi.feasibility import direction_feasibility


def _half_section():
    """5,280 ft E-W x 2,640 ft N-S — the N2/S2 tract shape."""
    sq = synthetic_section(5280.0)
    return scale(sq, xfact=1.0, yfact=0.5, origin=sq.centroid)


def _params(**kw):
    base = dict(formation="WCA_2", target_tvd_ft=11663, azimuth_deg=None,
                spacing_ft=880, setback_ft=330, min_lateral_ft=4000, anchor="auto")
    base.update(kw)
    return ScenarioParams(**base)


def test_direction_feasibility_half_section():
    parcel = _half_section()
    # N-S rows (grid-like az 0): max ~2,640 - 660 = 1,980 ft, hung across ~4,620 ft
    ns = direction_feasibility(parcel, 0.0, 330.0, label="grid", min_lateral_ft=4000.0)
    assert abs(ns.max_lateral_ft - 1980) < 60
    assert abs(ns.cross_extent_ft - 4620) < 60
    assert "min lateral" in ns.note          # flags that singles cannot place
    # E-W rows (long axis, az 90): max ~4,620 ft with ~1,980 ft to hang them
    ew = direction_feasibility(parcel, 90.0, 330.0, label="long-axis")
    assert abs(ew.max_lateral_ft - 4620) < 60
    assert abs(ew.cross_extent_ft - 1980) < 60


def test_parcel_feasibility_grid_vs_long_axis():
    parcel = _half_section()
    dirs = parcel_feasibility(parcel, 330.0, grid_azimuth_deg=0.0, min_lateral_ft=4000.0)
    assert [d.label for d in dirs] == ["grid", "long-axis"]
    # grid ~coincident with the long axis -> one row only
    dirs2 = parcel_feasibility(parcel, 330.0, grid_azimuth_deg=88.0)
    assert [d.label for d in dirs2] == ["grid"]
    # no grid control -> long axis only
    dirs3 = parcel_feasibility(parcel, 330.0, grid_azimuth_deg=None)
    assert [d.label for d in dirs3] == ["long-axis"]


def test_scan_ranks_long_axis_uturn_on_half_section():
    parcel = _half_section()
    base = _params()
    configs = scan_configs(parcel, base, [("grid", 0.0), ("long-axis", 90.0)])
    assert configs, "scan returned nothing"
    # every grid-direction config drops all wells (rows < 4,000 ft) -> zero footage;
    # the winner runs the long axis
    assert configs[0].azimuth_label == "long-axis"
    assert configs[0].completed_ft > 8000
    # ranked descending by footage
    fts = [c.completed_ft for c in configs]
    assert fts == sorted(fts, reverse=True)
    # u-turn rows under the leg-to-leg floor are not emitted (would dup singles)
    assert all(not (c.well_type == "uturn" and c.spacing_ft < base.uturn_min_leg_to_leg_ft)
               for c in configs)
    # scan rows reproduce: adopting the winner yields the same footage
    w = configs[0]
    _, _, feas = generate_scenario(
        parcel, _params(azimuth_deg=w.azimuth_deg, well_type=w.well_type,
                        spacing_ft=w.spacing_ft))
    assert abs(feas.total_completed_ft - w.completed_ft) < 1


def test_zero_well_note_names_the_workable_bearing():
    parcel = _half_section()
    # N-S laterals on the half-section: every candidate drops
    _, _, feas = generate_scenario(parcel, _params(azimuth_deg=0.0))
    assert feas.placed == 0
    assert "no wells" in feas.note
    assert "long axis" in feas.note and "azimuth override" in feas.note

    # u-turn zero includes the turn-trimmed completed ceiling
    _, _, feas_u = generate_scenario(
        parcel, _params(azimuth_deg=0.0, well_type="uturn", spacing_ft=1200))
    assert feas_u.placed == 0
    assert "U-turn completes" in feas_u.note

    # wine-rack zero carries the same hint
    _, _, rep = generate_wine_rack(
        parcel, _params(azimuth_deg=0.0, well_type="uturn", spacing_ft=1200),
        [Zone("WCA_2", 11663, spacing_ft=1200.0)])
    assert rep.total_wells == 0 and "no wells" in rep.note


def test_placed_runs_carry_no_hint():
    parcel = _half_section()
    _, _, feas = generate_scenario(parcel, _params(azimuth_deg=90.0))
    assert feas.placed > 0 and "no wells" not in feas.note

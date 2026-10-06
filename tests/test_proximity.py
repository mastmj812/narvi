import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import InventoryWell, Leg, apply_pdp_standoff  # noqa: E402

FT = 0.3048


def _well(name, tvd, heel_ft, toe_ft, category="generated"):
    h = (heel_ft[0] * FT, heel_ft[1] * FT)
    t = (toe_ft[0] * FT, toe_ft[1] * FT)
    leg = Leg(heel_xy=h, toe_xy=t, heel_lonlat=(0, 0), toe_lonlat=(0, 0),
              length_ft=0.0, gunbarrel_x_ft=0.0)
    return InventoryWell(
        scenario_id="", deal_id="", well_name=name, well_type="single", formation="WCB_1",
        target_tvd_ft=tvd, lateral_azimuth_deg=90.0, legs=[leg], turn=None,
        completed_lateral_ft=0.0, drilled_lateral_ft=0.0,
        nearest_neighbor_spacing_ft=0.0, setback_ft=0.0, category=category)


def test_vault_s2_geometry_flags_the_stick_over_the_parent():
    # University 45 20 1H: WCB_1 12,034' at cross +861; planned WCA_1 at 11,800'
    # one stick at +660 (on top of it) and one at -660 (the engineer's pin).
    parent = _well("4247537387", 12034, (-5000, 861), (5000, 861), "pdp")
    on_top = _well("WCA_1-01", 11800, (-2500, 660), (2500, 660))
    pinned = _well("WCA_1-02", 11800, (-2500, -660), (2500, -660))
    notes = apply_pdp_standoff([on_top, pinned], [parent])
    assert abs(on_top.pdp_gap_ft - 308.0) < 1.0           # hypot(201, 234)
    assert abs(on_top.pdp_gap_horiz_ft - 201.0) < 1.0
    assert on_top.pdp_gap_dtvd_ft == 234.0 and on_top.pdp_gap_well == "4247537387"
    assert abs(pinned.pdp_gap_ft - 1539.0) < 1.0
    assert len(notes) == 1 and "WCA_1-01" in notes[0] and "frac-hit" in notes[0]


def test_end_to_end_neighbour_is_not_co_extent():
    # a PDP toe-to-heel in the next unit along the same line: zero plan distance
    # at the tip, but no co-extent overlap -> not a frac-hit pairing
    pdp = _well("P", 11800, (2600, 0), (12600, 0), "pdp")
    w = _well("W", 11800, (-2500, 0), (2500, 0))
    assert apply_pdp_standoff([w], [pdp]) == []
    assert w.pdp_gap_ft is None and w.pdp_gap_well is None


def test_oblique_parent_measured_at_closest_approach_over_overlap():
    # a parent converging on the planned leg: gap = closest approach across the
    # shared stretch, not the midpoint offset
    pdp = _well("P", 11800, (-2500, 1000), (2500, 100), "pdp")
    w = _well("W", 11800, (-2500, 0), (2500, 0))
    apply_pdp_standoff([w], [pdp], min_gap_ft=500)
    assert abs(w.pdp_gap_ft - 100.0) < 1.0


def test_pdp_without_tvd_is_skipped():
    pdp = _well("P", 0.0, (-2500, 50), (2500, 50), "pdp")
    w = _well("W", 11800, (-2500, 0), (2500, 0))
    assert apply_pdp_standoff([w], [pdp]) == [] and w.pdp_gap_ft is None

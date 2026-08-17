"""DB-free tests for the bulk re-save differ (app.resave): fixture scenarios
in, diffs out. Covers the section-6 invariant check, axial azimuth deltas,
gunbarrel offset deltas, category-override round-trip survival (the toucan_2
defect class), novi_rep membership changes, and recipe reconstruction."""

from shapely.geometry import box

from app.api.scenarios import PreparedSave
from app.models import (
    SaveComposedRequest, SaveCurateRequest, SaveScenarioRequest,
)
from app.resave import (
    INV_TOL_FT, diff_scenario, override_problem_names, rebuild_request,
    render_diff, resolved_header_azimuth,
)
from narvi.placement import gunbarrel_offset_ft
from narvi.records import InventoryWell, Leg, ScenarioParams

PARCEL = box(0.0, 0.0, 2000.0, 3000.0)          # work CRS (m); centroid (1000, 1500)
ORIGIN = (PARCEL.centroid.x, PARCEL.centroid.y)


def _well(name, mid_x=1100.0, az=0.0, gb_az=None, category="generated",
          handoff=None, rep=None):
    """Single-leg N-S well whose midpoint sits at (mid_x, 1500). Its stored
    gunbarrel offset is projected under `gb_az` (defaults to `az`) — pass a
    different gb_az to fabricate a stale-frame well."""
    heel, toe = (mid_x, 1000.0), (mid_x, 2000.0)
    mid = ((heel[0] + toe[0]) / 2.0, (heel[1] + toe[1]) / 2.0)
    gb = gunbarrel_offset_ft(mid, gb_az if gb_az is not None else az, ORIGIN)
    leg = Leg(heel_xy=heel, toe_xy=toe, heel_lonlat=(0.0, 0.0),
              toe_lonlat=(0.0, 0.0), length_ft=3280.8,
              gunbarrel_x_ft=round(gb, 1))
    return InventoryWell(
        scenario_id="s1", deal_id="d1", well_name=name, well_type="single",
        formation="WCA_1", target_tvd_ft=10000.0, lateral_azimuth_deg=az,
        legs=[leg], turn=None, completed_lateral_ft=3280.8,
        drilled_lateral_ft=3280.8, nearest_neighbor_spacing_ft=0.0,
        setback_ft=0.0, category=category, handoff_category=handoff,
        novi_rep=rep)


def _params(az=None):
    return ScenarioParams(formation="WCA_1", target_tvd_ft=10000.0,
                          spacing_ft=880.0, setback_ft=330.0, azimuth_deg=az,
                          scenario_id="s1", deal_id="d1")


def _prepared(wells, frame_az=None, params_az=None, overrides=None):
    return PreparedSave(
        parcel=PARCEL, params=_params(params_az), wells=wells,
        summary={"category_overrides": overrides or {}},
        name="fixture", frame_azimuth_deg=frame_az)


def _header(az=57.0, overrides=None, name="fixture"):
    return {"deal_id": "d1", "scenario_id": "s1", "name": name,
            "azimuth_deg": az, "updated_at": "2026-08-01 00:00:00+00:00",
            "total_completed_ft": 3280.8,
            "summary": {"category_overrides": overrides or {}}}


# ---------------------------------------------------------------------------
# header azimuth + section-6 invariant
# ---------------------------------------------------------------------------

def test_header_azimuth_delta_is_axial():
    # 179.8 vs 0.2 are 0.4 deg apart on the axial circle, not 179.6
    stored = [_well("W1", az=179.8)]
    prepared = _prepared([_well("W1", az=179.8)], frame_az=0.2)
    d = diff_scenario(_header(az=179.8), stored, prepared, "curate", {})
    assert d.header_az_old == 179.8 and d.header_az_new == 0.2
    assert abs(d.header_az_delta - 0.4) < 0.01
    assert d.material


def test_resolved_header_azimuth_trust_order():
    w = _well("W1", az=33.3)
    assert resolved_header_azimuth(_prepared([w], frame_az=57.0)) == 57.0
    assert resolved_header_azimuth(_prepared([w])) == 33.3
    assert resolved_header_azimuth(_prepared([], params_az=12.0)) == 12.0


def test_invariant_flags_stale_stored_frame():
    # stored offsets were projected under 24 deg, but the header claims 57 deg
    # (the toucan azimuth defect shape): the stored-side invariant must blow up
    # while the recomputed side reproduces to ~0 ft.
    stored = [_well("W1", az=57.0, gb_az=24.0)]
    prepared = _prepared([_well("W1", az=57.0, gb_az=57.0)], frame_az=57.0)
    d = diff_scenario(_header(az=57.0), stored, prepared, "curate", {})
    assert d.invariant_stored_max_ft > INV_TOL_FT
    assert d.invariant_new_max_ft <= INV_TOL_FT
    assert "STALE FRAME" in render_diff(d)


def test_invariant_clean_when_frames_agree():
    stored = [_well("W1", az=57.0)]
    prepared = _prepared([_well("W1", az=57.0)], frame_az=57.0)
    d = diff_scenario(_header(az=57.0), stored, prepared, "curate", {})
    assert d.invariant_stored_max_ft <= INV_TOL_FT
    assert d.invariant_new_max_ft <= INV_TOL_FT
    assert not d.material
    assert "no material change" in render_diff(d)


# ---------------------------------------------------------------------------
# per-well deltas
# ---------------------------------------------------------------------------

def test_per_well_azimuth_and_offset_deltas():
    stored = [_well("W1", az=24.0)]
    prepared = _prepared([_well("W1", az=57.0)], frame_az=57.0)
    d = diff_scenario(_header(az=24.0), stored, prepared, "curate", {})
    assert len(d.az_deltas) == 1
    a = d.az_deltas[0]
    assert a.name == "W1" and abs(a.delta - 33.0) < 0.01
    assert len(d.offset_deltas) == 1          # gb reprojected under the new frame
    assert d.offset_deltas[0].name == "W1"
    assert d.material


def test_wells_added_and_removed():
    stored = [_well("W1"), _well("W2", mid_x=1200.0)]
    prepared = _prepared([_well("W1"), _well("W3", mid_x=1300.0)], frame_az=0.0)
    d = diff_scenario(_header(az=0.0), stored, prepared, "composed", {})
    assert d.wells_added == ["W3"] and d.wells_removed == ["W2"]
    assert d.material


# ---------------------------------------------------------------------------
# category-override round-trip survival
# ---------------------------------------------------------------------------

def test_overrides_survive_roundtrip():
    ov = {"W1": "UPSIDE"}
    stored = [_well("W1", handoff="UPSIDE")]
    prepared = _prepared([_well("W1", handoff="UPSIDE")], frame_az=0.0,
                         overrides=ov)
    d = diff_scenario(_header(az=0.0, overrides=ov), stored, prepared,
                      "composed", sent_overrides=ov)
    assert not d.overrides_lost and not d.overrides_pruned
    assert not d.material


def test_override_loss_is_loud():
    # the recomputed well no longer honors the persisted override — the class
    # of defect that flipped 4 wells PUD->UPSIDE in a shipped workbook
    ov = {"W1": "PUD"}
    stored = [_well("W1", handoff="PUD")]
    prepared = _prepared([_well("W1", handoff="UPSIDE")], frame_az=0.0,
                         overrides={})
    d = diff_scenario(_header(az=0.0, overrides=ov), stored, prepared,
                      "composed", sent_overrides={})
    assert d.overrides_lost == {"W1": "PUD"}
    assert d.material
    assert "OVERRIDE LOSS" in render_diff(d)


def test_override_pruned_when_well_leaves_plan():
    ov = {"W2": "UPSIDE"}
    stored = [_well("W1"), _well("W2", mid_x=1200.0, handoff="UPSIDE")]
    prepared = _prepared([_well("W1")], frame_az=0.0, overrides=ov)
    d = diff_scenario(_header(az=0.0, overrides=ov), stored, prepared,
                      "composed", sent_overrides=ov)
    assert d.overrides_pruned == {"W2": "UPSIDE"}
    assert "W2" in d.wells_removed
    assert "OVERRIDES PRUNED" in render_diff(d)


def test_qualified_rename_is_not_add_remove():
    # rows persisted before the name-qualification fix carry short generated
    # names; a re-save persists "<label> <name>". That is a rename, never an
    # add/remove pair, and per-well diffs must still pair up across it.
    stored = [_well("WCB_2-01", az=24.0)]
    prepared = _prepared([_well("fixture WCB_2-01", az=57.0)], frame_az=57.0)
    d = diff_scenario(_header(az=24.0), stored, prepared, "composed", {})
    assert d.wells_renamed == [("WCB_2-01", "fixture WCB_2-01")]
    assert not d.wells_added and not d.wells_removed
    assert len(d.az_deltas) == 1 and d.az_deltas[0].name == "WCB_2-01"
    assert d.material
    assert "renamed" in render_diff(d)


def test_override_honored_through_qualified_name():
    # override keys are ALWAYS the short client-side names; the recomputed well
    # carries the qualified label. Survival must resolve through the label —
    # this was a false "pruned" alarm on 12 live scenarios before the fix.
    ov = {"WCB_2-01": "PUD"}
    stored = [_well("fixture WCB_2-01", handoff="PUD")]
    prepared = _prepared([_well("fixture WCB_2-01", handoff="PUD")],
                         frame_az=0.0, overrides=ov)
    d = diff_scenario(_header(az=0.0, overrides=ov), stored, prepared,
                      "composed", sent_overrides=ov)
    assert not d.overrides_pruned and not d.overrides_lost
    assert not d.material


def test_override_problem_name_parsing():
    detail = ("override for unknown well 'pud-123'; "
              "override on existing producer '4201512345' (PDP is fixed)")
    assert override_problem_names(detail) == {"pud-123", "4201512345"}


# ---------------------------------------------------------------------------
# novi_rep membership
# ---------------------------------------------------------------------------

def test_novi_rep_membership_change():
    old_rep = {"mode": "neighborhood", "stick_ids": [1, 2, 3], "n": 3,
               "low_n": False}
    new_rep = {"mode": "neighborhood", "stick_ids": [1, 2], "n": 2,
               "low_n": True}
    stored = [_well("W1", rep=old_rep)]
    prepared = _prepared([_well("W1", rep=new_rep)], frame_az=0.0)
    d = diff_scenario(_header(az=0.0), stored, prepared, "composed", {})
    assert len(d.novi_rep_changes) == 1
    c = d.novi_rep_changes[0]
    assert c.old["n"] == 3 and c.new["n"] == 2 and c.new["low_n"] is True
    assert c.old["stick_ids"] == frozenset({1, 2, 3})
    assert d.material


def test_novi_rep_identical_sets_no_change():
    rep = {"mode": "self", "stick_ids": [42], "n": 1, "low_n": False}
    stored = [_well("W1", rep=dict(rep))]
    prepared = _prepared([_well("W1", rep=dict(rep))], frame_az=0.0)
    d = diff_scenario(_header(az=0.0), stored, prepared, "curate", {})
    assert not d.novi_rep_changes and not d.material


# ---------------------------------------------------------------------------
# recipe reconstruction (load-as-reset: everything rebases on model defaults)
# ---------------------------------------------------------------------------

_AOI = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


def test_rebuild_composed():
    header = {"deal_id": "d1", "scenario_id": "s1", "name": "plan a",
              "summary": {"mode": "composed",
                          "bench_sources": {"WCA_1": "generate"},
                          "categories": ["pdp", "pud"],
                          "culled_wells": ["x"],
                          "category_overrides": {"w": "PUD"},
                          "generate": {"params": {"spacing_ft": 880,
                                                  "setback_ft": 330},
                                       "zones": [], "source_azimuth": True,
                                       "buffer_ft": 5280.0}}}
    req, mode, reason = rebuild_request(header, _AOI)
    assert mode == "composed" and reason is None
    assert isinstance(req, SaveComposedRequest)
    assert req.name == "plan a" and req.culled_wells == ["x"]
    assert req.category_overrides == {"w": "PUD"}
    assert req.params.spacing_ft == 880
    assert req.force is False                 # load-as-reset: defaults, no residue


def test_rebuild_curate():
    header = {"deal_id": "d1", "scenario_id": "s1", "name": None,
              "summary": {"mode": "curate", "kept_benches": ["WCA_1"],
                          "categories": ["pdp"], "culled_wells": [],
                          "category_overrides": {}}}
    req, mode, reason = rebuild_request(header, _AOI)
    assert mode == "curate" and isinstance(req, SaveCurateRequest)
    assert req.kept_benches == ["WCA_1"]
    assert req.buffer_ft == 5280.0            # model default (not stored by curate)


def test_rebuild_legacy_generate():
    header = {"deal_id": "d1", "scenario_id": "s1", "name": "old",
              "summary": {"note": "n", "category_overrides": {},
                          "generate": {"params": {"spacing_ft": 880,
                                                  "setback_ft": 330},
                                       "mode": "single"}}}
    req, mode, reason = rebuild_request(header, _AOI)
    assert mode == "generate" and isinstance(req, SaveScenarioRequest)
    assert req.generate.parcel == _AOI


def test_rebuild_unresavable():
    req, mode, reason = rebuild_request(
        {"deal_id": "d", "scenario_id": "s", "summary": {"note": "pre-recipe"}},
        _AOI)
    assert req is None and "no re-save recipe" in reason
    req, mode, reason = rebuild_request(
        {"deal_id": "d", "scenario_id": "s",
         "summary": {"mode": "composed", "generate": {}}}, _AOI)
    assert req is None and "generate.params" in reason
    req, mode, reason = rebuild_request(
        {"deal_id": "d", "scenario_id": "s", "summary": {"mode": "curate"}},
        None)
    assert req is None and "AOI" in reason

"""Deal depth-window flagging (apply_depth_window) — the SOFT constraint.

The window is the engineer's correlated number (typed in the app), never a
value parsed from the land file: declared depths are often stratigraphic
equivalents of a reference log miles away (Toucan: declared 9,515' vs ~9,950'
correlated locally). Benches outside the window get flagged + noted, never
dropped — enabling a flagged bench in the app IS the override."""

from __future__ import annotations

from narvi.warehouse import BenchInfo, apply_depth_window


def _bench(formation: str, tvd: float | None, note: str = "") -> BenchInfo:
    return BenchInfo(formation, tvd, 3, 2, 1, 660.0, note)


def test_outside_window_flagged_and_noted_never_dropped():
    benches = [_bench("BS3_C", 8200.0), _bench("WCA_1", 10900.0)]
    apply_depth_window(benches, 0.0, 9950.0)
    assert benches[0].depth_allowed is True and benches[0].note == ""
    assert benches[1].depth_allowed is False
    assert "outside deal depth window" in benches[1].note
    assert "9,950 ft" in benches[1].note
    assert len(benches) == 2                       # soft: nothing removed


def test_open_ended_windows():
    b = [_bench("AVA_0", 7000.0), _bench("WCC", 11500.0)]
    apply_depth_window(b, 8000.0, None)            # floor only
    assert b[0].depth_allowed is False and "surface" not in b[0].note
    assert b[1].depth_allowed is True
    b2 = [_bench("AVA_0", 7000.0), _bench("WCC", 11500.0)]
    apply_depth_window(b2, None, 9950.0)           # ceiling only ("surface to X")
    assert b2[0].depth_allowed is True
    assert b2[1].depth_allowed is False and "surface" in b2[1].note


def test_no_window_and_no_median_stay_none():
    b = [_bench("BS2_S", 8000.0), _bench("WDFD", None)]
    apply_depth_window(b, None, None)              # no window -> untouched
    assert b[0].depth_allowed is None and b[1].depth_allowed is None
    apply_depth_window(b, 0.0, 9000.0)
    assert b[0].depth_allowed is True
    assert b[1].depth_allowed is None              # no median TVD: nothing to compare


def test_note_appends_to_existing():
    b = [_bench("WCB_1", 11000.0, note="thin control")]
    apply_depth_window(b, 0.0, 9950.0)
    assert b[0].note.startswith("thin control; outside deal depth window")


def test_benchinfo_positional_construction_regression():
    # depth_allowed (like n_supported before it) is APPENDED so existing
    # positional constructions keep working — this pins the field order.
    b = BenchInfo("WCA_1", 10900.0, 5, 2, 1, 880.0, "note", 3)
    assert b.n_supported == 3 and b.depth_allowed is None

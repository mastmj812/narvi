"""DB-free tests for the representative novi_intel set (detail->novi_rep).

Rule (agreed 2026-07-27): generated wells take the NEIGHBORHOOD set from
curated.intel_representative_sticks (same bench, PUD/RES within 1 mi, lateral
+/-25%); curated pud/res pass-throughs ARE novi sticks and compare against
their OWN forecast (mode 'self'); PDP producers and context wells carry no set.
narvi persists the SET only — the forecast median math lives in anduin.
"""

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi.persist import _well_from_detail
from narvi.records import InventoryWell, Leg
from narvi.warehouse import (
    NOVI_REP_LATERAL_TOL, NOVI_REP_RADIUS_M, apply_novi_rep,
)


def _well(name="w1", category="generated", context=False, stick_id=None,
          formation="WCA_1"):
    leg = Leg(heel_xy=(0.0, 0.0), toe_xy=(3000.0, 0.0), heel_lonlat=(-103.8, 31.9),
              toe_lonlat=(-103.77, 31.9), length_ft=9842.5, gunbarrel_x_ft=0.0)
    return InventoryWell(
        scenario_id="s", deal_id="d", well_name=name, well_type="single",
        formation=formation, target_tvd_ft=11500.0, lateral_azimuth_deg=90.0,
        legs=[leg], turn=None, completed_lateral_ft=9842.5, drilled_lateral_ft=9842.5,
        nearest_neighbor_spacing_ft=880.0, setback_ft=330.0, category=category,
        context=context, stick_id=stick_id)


class _FakeCursor:
    """Canned-response cursor: vintage query -> one date row; the rep-sticks
    function call -> the configured stick_id rows."""

    def __init__(self, rep_rows):
        self._rep_rows = rep_rows
        self._last_sql = ""
        self.calls = []

    def execute(self, sql, params=None):
        self._last_sql = sql
        self.calls.append((sql, params))

    def fetchone(self):
        assert "intel_vintage_date" in self._last_sql
        return ("2025-09-30",)

    def fetchall(self):
        assert "intel_representative_sticks" in self._last_sql
        return self._rep_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, rep_rows):
        self.cur = _FakeCursor(rep_rows)

    @contextmanager
    def cursor(self):
        yield self.cur


def test_mode_routing():
    wells = [
        _well("gen", category="generated"),
        _well("stick", category="pud", stick_id=4242),
        _well("resstick", category="res", stick_id=17),
        _well("producer", category="pdp"),
        _well("bg", category="pdp", context=True),
    ]
    conn = _FakeConn(rep_rows=[(1,), (2,), (3,), (4,)])
    apply_novi_rep(conn, wells)

    gen, stick, res, pdp, bg = wells
    assert gen.novi_rep == {
        "mode": "neighborhood", "stick_ids": [1, 2, 3, 4], "n": 4,
        "radius_m": NOVI_REP_RADIUS_M, "lateral_tol": NOVI_REP_LATERAL_TOL,
        "bench": "WCA_1", "intel_vintage": "2025-09-30", "low_n": False,
    }
    assert stick.novi_rep == {
        "mode": "self", "stick_ids": [4242], "n": 1, "bench": "WCA_1",
        "intel_vintage": "2025-09-30", "low_n": False,
    }
    assert res.novi_rep["mode"] == "self" and res.novi_rep["stick_ids"] == [17]
    assert pdp.novi_rep is None
    assert bg.novi_rep is None


def test_low_n_flagged_never_widened():
    w = _well()
    conn = _FakeConn(rep_rows=[(9,), (10,)])
    apply_novi_rep(conn, [w])
    assert w.novi_rep["n"] == 2
    assert w.novi_rep["low_n"] is True
    # exactly one rep-sticks call — no second, wider attempt
    rep_calls = [c for c in conn.cur.calls if "intel_representative_sticks" in c[0]]
    assert len(rep_calls) == 1
    # and the persisted params are the defaults the manifest will declare
    assert rep_calls[0][1]["radius"] == NOVI_REP_RADIUS_M
    assert rep_calls[0][1]["tol"] == NOVI_REP_LATERAL_TOL


def test_bimodal_bench_suffix_stripped():
    w = _well(formation="WCA_1_b")
    conn = _FakeConn(rep_rows=[(1,), (2,), (3,)])
    apply_novi_rep(conn, [w])
    rep_call = [c for c in conn.cur.calls if "intel_representative_sticks" in c[0]][0]
    assert rep_call[1]["bench"] == "WCA_1"
    assert w.novi_rep["bench"] == "WCA_1"


def test_dbfree_degrade():
    """conn=None: self entries still written (vintage None), generated stay
    unscored, and a pud stick without its stick_id can't self-reference."""
    wells = [
        _well("gen"),
        _well("stick", category="pud", stick_id=7),
        _well("legacy", category="pud", stick_id=None),
    ]
    apply_novi_rep(None, wells)
    assert wells[0].novi_rep is None
    assert wells[1].novi_rep["mode"] == "self"
    assert wells[1].novi_rep["intel_vintage"] is None
    assert wells[2].novi_rep is None


def test_novi_rep_survives_detail_roundtrip():
    w = _well(category="pud", stick_id=4242)
    apply_novi_rep(None, [w])
    detail = json.loads(json.dumps(asdict(w)))     # tuples -> lists, as JSONB does
    rt = _well_from_detail(detail)
    assert rt.stick_id == 4242
    assert rt.novi_rep == w.novi_rep
    assert rt == w

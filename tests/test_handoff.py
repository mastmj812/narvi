"""DB-free tests for the workbook-handoff classification (PDP/PUD/UPSIDE).

The rule (agreed 2026-07-22): existing producers -> PDP; planned sticks with
pdp_count_3mi >= 3 qualifying offsets -> PUD; <= 2 or unscored -> UPSIDE. The
narvi UI can override PUD/UPSIDE per well; the persisted handoff_category is
what the anduin Blue Ox exporter reads.
"""

import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi.persist import _well_from_detail
from narvi.records import InventoryWell, Leg
from narvi.warehouse import apply_handoff_support, derive_handoff_category


def _well(name="w1", category="generated", pdp_count_3mi=None, context=False,
          handoff_category=None):
    leg = Leg(heel_xy=(0.0, 0.0), toe_xy=(3000.0, 0.0), heel_lonlat=(-103.8, 31.9),
              toe_lonlat=(-103.77, 31.9), length_ft=9842.5, gunbarrel_x_ft=0.0)
    return InventoryWell(
        scenario_id="s", deal_id="d", well_name=name, well_type="single",
        formation="WCA_1", target_tvd_ft=11500.0, lateral_azimuth_deg=90.0,
        legs=[leg], turn=None, completed_lateral_ft=9842.5, drilled_lateral_ft=9842.5,
        nearest_neighbor_spacing_ft=880.0, setback_ft=330.0, category=category,
        context=context, pdp_count_3mi=pdp_count_3mi, handoff_category=handoff_category)


def test_derive_rule():
    assert derive_handoff_category(_well(category="pdp")) == "PDP"
    assert derive_handoff_category(_well(pdp_count_3mi=3)) == "PUD"
    assert derive_handoff_category(_well(pdp_count_3mi=7)) == "PUD"
    assert derive_handoff_category(_well(pdp_count_3mi=2)) == "UPSIDE"
    assert derive_handoff_category(_well(pdp_count_3mi=0)) == "UPSIDE"
    assert derive_handoff_category(_well(pdp_count_3mi=None)) == "UPSIDE"
    # curated pud/res sticks follow the same count rule, not their Novi label
    assert derive_handoff_category(_well(category="pud", pdp_count_3mi=1)) == "UPSIDE"
    assert derive_handoff_category(_well(category="res", pdp_count_3mi=5)) == "PUD"


def test_apply_handoff_support_dbfree():
    wells = [
        _well("a", category="pdp"),
        _well("b", pdp_count_3mi=4),
        _well("c", pdp_count_3mi=None),           # unscored, no conn -> UPSIDE
        _well("d", context=True),                  # background: untouched
        _well("e", pdp_count_3mi=0, handoff_category="PUD"),  # existing override wins
    ]
    apply_handoff_support(None, wells)
    assert [w.handoff_category for w in wells] == ["PDP", "PUD", "UPSIDE", None, "PUD"]


def test_handoff_fields_survive_detail_roundtrip():
    w = _well(pdp_count_3mi=5, handoff_category="PUD")
    detail = json.loads(json.dumps(asdict(w)))     # tuples -> lists, as JSONB does
    rt = _well_from_detail(detail)
    assert rt.pdp_count_3mi == 5
    assert rt.handoff_category == "PUD"
    assert rt == w

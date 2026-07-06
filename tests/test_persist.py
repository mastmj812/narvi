import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import ScenarioParams, generate_scenario, synthetic_section
from narvi.persist import _split_statements, _well_from_detail


def test_well_detail_survives_json_roundtrip():
    # The DB stores each well as `detail` jsonb; JSON turns the coordinate tuples
    # into lists, so _well_from_detail must coerce them back. Exercise the exact
    # path (asdict -> json -> _well_from_detail) for both a U-turn and a single.
    parcel = synthetic_section()
    p = ScenarioParams(formation="WCA_1", target_tvd_ft=11500, azimuth_deg=0.0,
                       spacing_ft=990, setback_ft=200, min_lateral_ft=4000,
                       anchor="center", well_type="uturn")
    wells, _, _ = generate_scenario(parcel, p)
    assert any(w.turn for w in wells) and any(w.turn is None for w in wells)
    for w in wells:
        detail = json.loads(json.dumps(asdict(w)))   # tuples -> lists, as JSONB does
        assert _well_from_detail(detail) == w        # reconstructed exactly


def test_curate_provenance_survives_roundtrip():
    # A curate baseline well carries Novi provenance (category / recon_status /
    # novi_wellname) that must reload faithfully — the hand-off depends on it.
    from narvi import InventoryWell, Leg

    leg = Leg(heel_xy=(1.0, 2.0), toe_xy=(3.0, 4.0), heel_lonlat=(-103.1, 31.9),
              toe_lonlat=(-103.2, 31.95), length_ft=5200.0, gunbarrel_x_ft=-440.0)
    w = InventoryWell(
        scenario_id="s", deal_id="d", well_name="NOVI-7", well_type="single",
        formation="WCA_1", target_tvd_ft=11000.0, lateral_azimuth_deg=165.3,
        legs=[leg], turn=None, completed_lateral_ft=5200.0, drilled_lateral_ft=5200.0,
        nearest_neighbor_spacing_ft=880.0, setback_ft=330.0,
        category="pud", novi_wellname="Hecker 1H", edited=False, recon_status="remaining_pud")
    detail = json.loads(json.dumps(asdict(w)))
    rt = _well_from_detail(detail)
    assert rt == w
    assert rt.category == "pud" and rt.recon_status == "remaining_pud"
    assert rt.novi_wellname == "Hecker 1H"


def test_split_ignores_semicolons_in_string_literals():
    # the COMMENT string contains a ';' that must NOT split the statement
    sql = (
        "CREATE SCHEMA IF NOT EXISTS narvi;\n"
        "COMMENT ON SCHEMA narvi IS\n"
        "'app write-back; not in the ETL chain';\n"
        "CREATE TABLE narvi.t (id int);\n"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 3
    assert stmts[1] == "COMMENT ON SCHEMA narvi IS\n'app write-back; not in the ETL chain'"


def test_split_strips_line_comments_and_blank_statements():
    sql = (
        "-- a leading comment\n"
        "CREATE TABLE t (id int);  -- trailing comment with ; inside\n"
        "\n"
        ";\n"  # empty statement -> dropped
        "SELECT 1;\n"
    )
    stmts = _split_statements(sql)
    assert stmts == ["CREATE TABLE t (id int)", "SELECT 1"]

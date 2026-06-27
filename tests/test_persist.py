import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi.persist import _split_statements


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

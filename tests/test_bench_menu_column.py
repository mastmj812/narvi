"""The generation bench menu is the basin's FULL stratigraphic column, in column
order — local evidence never decides which benches exist (Gator Tails 44-5-8:
no BS1_S within 1 mi, so BS1_S vanished from the menu and couldn't be
generated). TVD precedence: ring producers -> ring Novi sticks -> nearest
producers (widened) -> nearest Novi sticks (widened) -> None."""

from contextlib import contextmanager

from shapely.geometry import box

from narvi.warehouse import STRAT_COLUMN, available_benches


class _Cursor:
    """Answers each query by what it reads; widened tiers only see the codes
    still missing (asserted via the `codes` bind)."""

    def __init__(self, basin, ring_producers, ring_sticks, far_producers, far_sticks):
        self.basin = basin
        self.ring_producers = ring_producers   # [(fb, n, med)]
        self.ring_sticks = ring_sticks         # [(fb, tvd, dist_m)]
        self.far_producers = far_producers
        self.far_sticks = far_sticks
        self.rows: list = []
        self.asked: list[tuple[str, list[str]]] = []

    def execute(self, sql, params=None):
        params = params or {}
        if "basin_blueox FROM" in sql:
            self.rows = [(self.basin,)] if self.basin else []
        elif "GROUP BY 1, 2" in sql:                       # ring Novi counts
            self.rows = []
        elif "percentile_cont" in sql:                     # ring producers
            self.rows = list(self.ring_producers)
        elif "row_number()" in sql:
            codes = params["codes"]
            ring = params["far"] < 5000
            if "wells_enriched" in sql:
                src, tier = self.far_producers, "far_producers"
            else:
                src, tier = (self.ring_sticks, "ring_sticks") if ring else (self.far_sticks, "far_sticks")
            self.asked.append((tier, list(codes)))
            self.rows = [r for r in src if r[0] in codes]
        else:                                              # azimuth / spacing
            self.rows = []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    @contextmanager
    def cursor(self):
        yield self.cur


_PARCEL = box(600000, 3500000, 601600, 3503200)   # work CRS (UTM 13N), metres


def _run(**kw):
    cur = _Cursor(**{"basin": "delaware", "ring_producers": [], "ring_sticks": [],
                     "far_producers": [], "far_sticks": [], **kw})
    return available_benches(_Conn(cur), _PARCEL, buffer_ft=5280.0), cur


def test_full_delaware_column_always_listed_in_order():
    out, _ = _run()
    assert [b.formation for b in out] == STRAT_COLUMN["delaware"]
    assert [b.strat_rank for b in out] == list(range(len(STRAT_COLUMN["delaware"])))
    assert all(b.median_tvd_ft is None and b.tvd_basis is None for b in out)


def test_column_order_beats_tvd_order():
    # WCA_2 shallower than WCA_1 (noisy labels) must NOT reorder the column
    out, _ = _run(ring_producers=[("WCA_1", 16, 12154.0), ("WCA_2", 15, 12101.0)])
    codes = [b.formation for b in out]
    assert codes.index("WCA_1") < codes.index("WCA_2")


def test_midland_basin_and_unknown_fallback():
    out, _ = _run(basin="midland")
    assert [b.formation for b in out] == STRAT_COLUMN["midland"]
    out, _ = _run(basin=None)
    assert [b.formation for b in out] == STRAT_COLUMN["delaware"]


def test_off_column_code_kept_after_column():
    out, _ = _run(ring_producers=[("OTHER", 3, 5000.0)])
    assert out[-1].formation == "OTHER" and out[-1].strat_rank is None


def test_tvd_tier_precedence():
    out, cur = _run(
        ring_producers=[("BS2_C", 1, 10733.0)],
        ring_sticks=[("BS2_C", 9000.0, 0.0), ("AVA_0", 9293.0, 0.0)],
        far_producers=[("AVA_0", 8000.0, 15000.0), ("BS1_S", 10000.0, 4000.0),
                       ("BS1_S", 10200.0, 9000.0)],
        far_sticks=[("BS1_S", 1.0, 1.0), ("WCD", 13000.0, 12000.0)],
    )
    by = {b.formation: b for b in out}
    # ring producer beats ring Novi, even thin (prior precedence), and is labelled
    assert by["BS2_C"].median_tvd_ft == 10733.0
    assert by["BS2_C"].tvd_local is True and "thin" in by["BS2_C"].tvd_basis
    # ring Novi beats a widened producer
    assert by["AVA_0"].median_tvd_ft == 9293.0 and by["AVA_0"].tvd_local is True
    # nothing in the ring -> nearest producers, flagged non-local with reach
    assert by["BS1_S"].median_tvd_ft == 10100.0 and by["BS1_S"].tvd_local is False
    assert "producers, out to 5.6 mi" in by["BS1_S"].tvd_basis
    # no producers within the far radius -> nearest Novi sticks
    assert by["WCD"].median_tvd_ft == 13000.0 and "Novi sticks" in by["WCD"].tvd_basis
    # widened tiers are only asked about benches still missing
    far_asks = dict(cur.asked)
    assert "BS2_C" not in far_asks["far_producers"] and "AVA_0" not in far_asks["far_producers"]
    assert "BS1_S" not in far_asks["far_sticks"]
    assert by["STRN"].median_tvd_ft is None

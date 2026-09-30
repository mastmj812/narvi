"""Landing-TVD medians come from PRODUCING wells only — permits, cancelled
permits and DUCs carry planned depths, not landings (Rally Caps 4-5: 22
cancelled permits at 12,000–13,000 ft set the WCC median over 1 producer)."""

from contextlib import contextmanager

from shapely.geometry import box

from narvi.warehouse import available_benches, landing_tvd_stats


class _Cursor:
    def __init__(self):
        self.sqls: list[str] = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.cur = _Cursor()

    @contextmanager
    def cursor(self):
        yield self.cur


_PARCEL = box(600000, 3500000, 601600, 3503200)   # work CRS (UTM 13N), metres


def test_landing_tvd_stats_filters_to_producers():
    conn = _Conn()
    st = landing_tvd_stats(conn, _PARCEL, "WCC")
    assert st.median_tvd_ft is None               # nothing returned -> no stats
    assert "first_production_date IS NOT NULL" in conn.cur.sqls[0]


def test_bench_menu_producer_median_filters_to_producers():
    conn = _Conn()
    available_benches(conn, _PARCEL)
    wells_sql = [s for s in conn.cur.sqls if "curated.wells_enriched" in s]
    assert wells_sql, "bench menu no longer reads producers from wells_enriched"
    assert "first_production_date IS NOT NULL" in wells_sql[0]

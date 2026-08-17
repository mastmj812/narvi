"""Bulk scenario re-save — dry-run diff by default, --apply to write.

Every engine/semantics fix leaves persisted scenarios stale until each one is
re-loaded and re-saved ("merged code does not retro-fix persisted rows"); done
by hand at least four times, and one missed re-save shipped a category-override
flip to the finance counterparty. This tool automates the sweep:

1. Enumerates every scenario in narvi.scenario.
2. Rebuilds each save request from the persisted recipe (summary jsonb) plus
   the stored AOI geometry — the server-side equivalent of the client's
   load-as-reset: every request rebases on the Pydantic model defaults, and
   nothing carries over from any other scenario.
3. Recomputes through the EXACT read-only prepare half of the save endpoints
   (app.api.scenarios.prepare_save / prepare_curate / prepare_composed), so
   _guard_override_drop, _classify_for_handoff, apply_novi_rep,
   qualify_planned_names and frame-azimuth resolution all apply. Never raw SQL
   writes into narvi.*.
4. Prints a per-scenario diff: header/per-well azimuth deltas (AXIAL distance,
   never abs(a-b)), gunbarrel offset deltas, the section-6 invariant check
   (every stored offset must reproduce from header azimuth + parcel centroid
   to ~0 ft), category-override survival, and novi_rep membership changes.
5. --apply re-saves scenarios with material diffs through the SAME endpoint
   functions the HTTP save uses (guards included). Re-saves bump updated_at,
   which flips pinned anduin blueox configs to a stale badge — the report
   lists every scenario that will need a re-pin.

Run from backend/:
    ..\\.venv\\Scripts\\python.exe -m app.resave [--deal D] [--scenario S] [--apply]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field

import psycopg
from fastapi import HTTPException
from pydantic import ValidationError

from narvi import persist
from narvi.placement import gunbarrel_offset_ft
from narvi.records import InventoryWell
from narvi.warehouse import _axial_dist_deg, get_connection

from .api.scenarios import (
    PreparedSave, prepare_composed, prepare_curate, prepare_save,
    save, save_composed, save_curate,
)
from .models import (
    GenerateRequest, SaveComposedRequest, SaveCurateRequest, SaveScenarioRequest,
)

# Tolerances. Stored gunbarrel offsets and azimuths are rounded to 0.1, and the
# AOI round-trips EWKT -> geometry -> GeoJSON between save and re-save, so a
# few tenths of a foot of reprojection jitter is noise, not signal.
AZ_TOL_DEG = 0.05      # axial degrees
GB_TOL_FT = 0.5        # per-leg offset delta worth reporting
INV_TOL_FT = 0.5       # section-6 "reproduces to ~0 ft" bar (values stored at 0.1)


# ---------------------------------------------------------------------------
# Pure diff layer (DB-free, unit-tested in backend/tests/test_resave.py)
# ---------------------------------------------------------------------------

@dataclass
class WellAzDelta:
    name: str
    old: float
    new: float
    delta: float          # axial degrees


@dataclass
class LegOffsetDelta:
    name: str
    leg: int
    old: float
    new: float
    delta: float          # ft


@dataclass
class NoviRepChange:
    name: str
    old: dict | None      # {mode, n, low_n, stick_ids-set} summaries
    new: dict | None


@dataclass
class ScenarioDiff:
    deal_id: str
    scenario_id: str
    name: str | None
    mode: str
    updated_at: str
    error: str | None = None

    n_wells_old: int = 0
    n_wells_new: int = 0
    total_completed_ft_old: float | None = None
    total_completed_ft_new: float | None = None

    header_az_old: float | None = None
    header_az_new: float | None = None
    header_az_delta: float | None = None      # axial degrees

    wells_added: list[str] = field(default_factory=list)
    wells_removed: list[str] = field(default_factory=list)
    # stored short generated names that a re-save persists under the qualified
    # label ("WCB_2-01" -> "theCan_north WCB_2-01"): pre-qualification-fix rows
    wells_renamed: list[tuple[str, str]] = field(default_factory=list)
    az_deltas: list[WellAzDelta] = field(default_factory=list)
    offset_deltas: list[LegOffsetDelta] = field(default_factory=list)

    # section-6 invariant: max |gunbarrel_x_ft - offset(mid, header_az, centroid)|
    invariant_stored_max_ft: float | None = None   # stored rows vs STORED header az
    invariant_new_max_ft: float | None = None      # recomputed rows vs NEW header az

    handoff_changes: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    overrides_before: dict = field(default_factory=dict)
    overrides_sent: dict = field(default_factory=dict)
    overrides_lost: dict = field(default_factory=dict)      # LOUD: value not honored
    overrides_pruned: dict = field(default_factory=dict)    # well left the plan / went PDP

    novi_rep_changes: list[NoviRepChange] = field(default_factory=list)

    legacy_culls_unrecorded: bool = False

    @property
    def material(self) -> bool:
        """Would a re-save persist something different (beyond noise)?"""
        return bool(
            self.error is None and (
                self.wells_added or self.wells_removed or self.wells_renamed
                or (self.header_az_delta is not None and self.header_az_delta > AZ_TOL_DEG)
                or self.az_deltas or self.offset_deltas or self.handoff_changes
                or self.overrides_lost or self.overrides_pruned
                or self.novi_rep_changes
            )
        )


def resolved_header_azimuth(ps: PreparedSave) -> float | None:
    """The azimuth persist.save_scenario would store — keep in lockstep with
    its `resolved_az` expression."""
    if ps.frame_azimuth_deg is not None:
        return ps.frame_azimuth_deg
    if ps.wells:
        return ps.wells[0].lateral_azimuth_deg
    return ps.params.azimuth_deg


def invariant_max_dev_ft(
    wells: list[InventoryWell], azimuth_deg: float | None,
    origin_xy: tuple[float, float],
) -> float | None:
    """Section-6 invariant: worst |stored offset - reprojected offset| over every
    leg, reprojecting each leg midpoint through THE canonical frame (header
    azimuth + parcel centroid). None when there is no azimuth or no legs."""
    if azimuth_deg is None:
        return None
    worst: float | None = None
    for w in wells:
        for leg in w.legs:
            mid = ((leg.heel_xy[0] + leg.toe_xy[0]) / 2.0,
                   (leg.heel_xy[1] + leg.toe_xy[1]) / 2.0)
            want = gunbarrel_offset_ft(mid, azimuth_deg, origin_xy)
            dev = abs(leg.gunbarrel_x_ft - want)
            worst = dev if worst is None else max(worst, dev)
    return worst


def _rep_summary(rep: dict | None) -> dict | None:
    if rep is None:
        return None
    return {
        "mode": rep.get("mode"),
        "n": rep.get("n"),
        "low_n": rep.get("low_n"),
        "stick_ids": frozenset(rep.get("stick_ids") or ()),
    }


def diff_scenario(
    header: dict,
    stored_wells: list[InventoryWell],
    prepared: PreparedSave,
    mode: str,
    sent_overrides: dict,
    pruned_overrides: dict | None = None,
) -> ScenarioDiff:
    """Pure diff between the persisted scenario and the freshly recomputed one."""
    d = ScenarioDiff(
        deal_id=header["deal_id"], scenario_id=header["scenario_id"],
        name=header.get("name"), mode=mode,
        updated_at=str(header.get("updated_at") or ""),
    )
    d.legacy_culls_unrecorded = mode == "generate"
    d.n_wells_old = len(stored_wells)
    d.n_wells_new = len(prepared.wells)
    d.total_completed_ft_old = header.get("total_completed_ft")
    d.total_completed_ft_new = round(
        sum(w.completed_lateral_ft for w in prepared.wells), 1)

    old_by = {w.well_name: w for w in stored_wells}
    new_by = {w.well_name: w for w in prepared.wells}

    # Name matching must tolerate qualify_planned_names: rows persisted before
    # the name-qualification fix (and override keys, which ALWAYS use the short
    # client-side working names) carry "WCB_2-01" where a re-save persists
    # "<label> WCB_2-01". label mirrors the save paths: req.name or deal_id.
    label = (prepared.name or header["deal_id"] or "").strip()

    def _match(stored_name: str) -> str | None:
        if stored_name in new_by:
            return stored_name
        if label and f"{label} {stored_name}" in new_by:
            return f"{label} {stored_name}"
        return None

    mapping = {on: _match(on) for on in old_by}
    matched_new = {nn for nn in mapping.values() if nn is not None}
    d.wells_renamed = sorted(
        (o, n) for o, n in mapping.items() if n is not None and n != o)
    d.wells_removed = sorted(o for o, n in mapping.items() if n is None)
    d.wells_added = sorted(new_by.keys() - matched_new)

    # header / scenario frame azimuth
    d.header_az_old = header.get("azimuth_deg")
    d.header_az_new = resolved_header_azimuth(prepared)
    if d.header_az_old is not None and d.header_az_new is not None:
        d.header_az_delta = round(
            _axial_dist_deg(float(d.header_az_old), float(d.header_az_new)), 2)

    origin = (prepared.parcel.centroid.x, prepared.parcel.centroid.y)
    az_old = float(d.header_az_old) if d.header_az_old is not None else None
    d.invariant_stored_max_ft = invariant_max_dev_ft(stored_wells, az_old, origin)
    d.invariant_new_max_ft = invariant_max_dev_ft(
        prepared.wells, d.header_az_new, origin)

    for name in sorted(o for o, n in mapping.items() if n is not None):
        ow, nw = old_by[name], new_by[mapping[name]]
        adelta = _axial_dist_deg(ow.lateral_azimuth_deg, nw.lateral_azimuth_deg)
        if adelta > AZ_TOL_DEG:
            d.az_deltas.append(WellAzDelta(
                name, ow.lateral_azimuth_deg, nw.lateral_azimuth_deg,
                round(adelta, 2)))
        for i, (ol, nl) in enumerate(zip(ow.legs, nw.legs)):
            gdelta = nl.gunbarrel_x_ft - ol.gunbarrel_x_ft
            if abs(gdelta) > GB_TOL_FT:
                d.offset_deltas.append(LegOffsetDelta(
                    name, i, ol.gunbarrel_x_ft, nl.gunbarrel_x_ft, round(gdelta, 1)))
        if ow.handoff_category != nw.handoff_category:
            d.handoff_changes.append((name, ow.handoff_category, nw.handoff_category))
        oldr, newr = _rep_summary(ow.novi_rep), _rep_summary(nw.novi_rep)
        if oldr != newr:
            d.novi_rep_changes.append(NoviRepChange(name, oldr, newr))

    # category-override survival: every persisted override must either be
    # honored on the recomputed well or accounted for (well left the plan /
    # became a producer). Silent loss shipped a PUD->UPSIDE flip once (toucan_2)
    # — any loss here is rendered loudly by the report.
    before = (header.get("summary") or {}).get("category_overrides") or {}
    d.overrides_before = dict(before)
    d.overrides_sent = dict(sent_overrides)
    d.overrides_pruned = dict(pruned_overrides or {})
    for name, cat in before.items():
        # override keys are the short working names; the persisted well may
        # carry the qualified label — resolve through the same mapping rule
        w = new_by.get(name)
        if w is None and label:
            w = new_by.get(f"{label} {name}")
        if w is None or w.category == "pdp":
            d.overrides_pruned.setdefault(name, cat)
        elif w.handoff_category != cat:
            d.overrides_lost[name] = cat
    return d


# ---------------------------------------------------------------------------
# Request reconstruction from the persisted recipe
# ---------------------------------------------------------------------------

def rebuild_request(header: dict, aoi_geojson: dict | None):
    """(request, mode, reason). request is None (with a reason) when the row
    predates the recipe or the recipe is incomplete. mode is one of
    'composed' | 'curate' | 'generate' | 'unknown'."""
    summary = header.get("summary") or {}
    mode = summary.get("mode")
    deal_id, scenario_id = header["deal_id"], header["scenario_id"]
    name = header.get("name")
    overrides = summary.get("category_overrides") or {}
    if aoi_geojson is None:
        return None, mode or "unknown", "no stored AOI geometry"
    try:
        if mode == "composed":
            gen = summary.get("generate") or {}
            if not gen.get("params"):
                return None, "composed", "recipe missing generate.params"
            req = SaveComposedRequest(
                deal_id=deal_id, scenario_id=scenario_id, name=name,
                parcel=aoi_geojson,
                bench_sources=summary.get("bench_sources") or {},
                categories=summary.get("categories") or ["pdp", "pud", "res"],
                culled_wells=summary.get("culled_wells") or [],
                params=gen["params"], zones=gen.get("zones") or [],
                source_azimuth=gen.get("source_azimuth", True),
                buffer_ft=gen.get("buffer_ft", 5280.0),
                category_overrides=overrides,
                deal_terms=summary.get("deal_terms"))
            return req, "composed", None
        if mode == "curate":
            req = SaveCurateRequest(
                deal_id=deal_id, scenario_id=scenario_id, name=name,
                parcel=aoi_geojson,
                kept_benches=summary.get("kept_benches") or [],
                categories=summary.get("categories") or ["pdp", "pud", "res"],
                culled_wells=summary.get("culled_wells") or [],
                category_overrides=overrides)
            return req, "curate", None
        if summary.get("generate"):
            # legacy generate save: culls were baked out and NOT recorded in the
            # recipe — a re-save may resurrect culled wells (flagged in the diff).
            req = SaveScenarioRequest(
                deal_id=deal_id, scenario_id=scenario_id, name=name,
                generate=GenerateRequest(
                    parcel=aoi_geojson, **summary["generate"]),
                category_overrides=overrides)
            return req, "generate", None
    except ValidationError as exc:
        return None, mode or "unknown", f"recipe failed validation: {exc}"
    return None, mode or "unknown", "no re-save recipe in summary (pre-recipe vintage)"


_PREPARE = {
    SaveComposedRequest: prepare_composed,
    SaveCurateRequest: prepare_curate,
    SaveScenarioRequest: prepare_save,
}
_SAVE = {
    SaveComposedRequest: save_composed,
    SaveCurateRequest: save_curate,
    SaveScenarioRequest: save,
}

_OVERRIDE_PROBLEM_RE = re.compile(
    r"override (?:for unknown well|on existing producer) '([^']+)'")


def override_problem_names(detail: str) -> set[str]:
    """Well names out of _classify_for_handoff's 400 detail — overrides that no
    longer target a live planned well (vanished stick / now a producer)."""
    return set(_OVERRIDE_PROBLEM_RE.findall(detail))


def prepare_with_prune(req, conn):
    """Run the endpoint's prepare path; if stored overrides name wells that no
    longer exist in the recomputed plan (400 from _classify_for_handoff), prune
    exactly those and retry once. Returns (prepared, pruned_dict, request_used).
    The pruned set is reported loudly — it is a real difference between what
    was persisted and what a re-save can honor. Dry-run-only helper: the retry
    transaction is re-pinned READ ONLY."""
    fn = _PREPARE[type(req)]
    try:
        return fn(req, conn), {}, req
    except HTTPException as exc:
        if exc.status_code != 400 or not isinstance(exc.detail, str):
            raise
        bad = override_problem_names(exc.detail)
        if not bad:
            raise
        conn.rollback()          # clear the aborted-read state before the retry
        conn.execute("SET TRANSACTION READ ONLY")
        overrides = dict(req.category_overrides)
        pruned = {n: overrides.pop(n) for n in bad if n in overrides}
        req2 = req.model_copy(update={"category_overrides": overrides})
        return fn(req2, conn), pruned, req2


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _fmt_az(v) -> str:
    return f"{float(v):.1f} deg" if v is not None else "None"


def render_diff(d: ScenarioDiff) -> str:
    """One scenario's diff block, plain ASCII."""
    hdr = f"{d.deal_id}/{d.scenario_id}"
    if d.name:
        hdr += f"  ({d.name})"
    lines = ["=" * 78, f"{hdr}  [{d.mode}]  updated_at={d.updated_at}"]
    if d.error:
        lines.append(f"  ERROR / SKIPPED: {d.error}")
        return "\n".join(lines)

    lines.append(f"  status: {'CHANGED - re-save recommended' if d.material else 'no material change'}")
    lines.append(f"  wells: {d.n_wells_old} stored -> {d.n_wells_new} recomputed; "
                 f"completed ft: {d.total_completed_ft_old} -> {d.total_completed_ft_new}")

    az = f"  header azimuth: {_fmt_az(d.header_az_old)} -> {_fmt_az(d.header_az_new)}"
    if d.header_az_delta is not None:
        az += f"  (axial delta {d.header_az_delta:.2f} deg)"
    lines.append(az)

    inv_s = ("n/a" if d.invariant_stored_max_ft is None
             else f"{d.invariant_stored_max_ft:.1f} ft")
    inv_n = ("n/a" if d.invariant_new_max_ft is None
             else f"{d.invariant_new_max_ft:.1f} ft")
    stale = (d.invariant_stored_max_ft is not None
             and d.invariant_stored_max_ft > INV_TOL_FT)
    bad_new = (d.invariant_new_max_ft is not None
               and d.invariant_new_max_ft > INV_TOL_FT)
    lines.append(f"  sec-6 invariant (max |offset - reprojection|): "
                 f"stored {inv_s}{'  ** STALE FRAME **' if stale else ''}; "
                 f"recomputed {inv_n}"
                 f"{'  ** INTERNAL INCONSISTENCY - investigate **' if bad_new else ''}")

    if d.wells_added:
        note = " (legacy recipe carries no culls - added wells may be resurrected culls; review before apply)" \
            if d.legacy_culls_unrecorded else ""
        lines.append(f"  wells added ({len(d.wells_added)}){note}: "
                     + ", ".join(d.wells_added[:12])
                     + (" ..." if len(d.wells_added) > 12 else ""))
    if d.wells_removed:
        lines.append(f"  wells removed ({len(d.wells_removed)}): "
                     + ", ".join(d.wells_removed[:12])
                     + (" ..." if len(d.wells_removed) > 12 else ""))
    if d.wells_renamed:
        lines.append(f"  wells renamed ({len(d.wells_renamed)}) - stored short "
                     f"names gain the scenario label on re-save: "
                     + ", ".join(f"{o} -> {n}" for o, n in d.wells_renamed[:6])
                     + (" ..." if len(d.wells_renamed) > 6 else ""))

    for a in d.az_deltas:
        lines.append(f"    az   {a.name}: {a.old:.1f} -> {a.new:.1f} deg "
                     f"(axial delta {a.delta:.2f})")
    for o in d.offset_deltas:
        lines.append(f"    gbx  {o.name} leg{o.leg}: {o.old:.1f} -> {o.new:.1f} ft "
                     f"(delta {o.delta:+.1f})")
    for name, old, new in d.handoff_changes:
        lines.append(f"    cat  {name}: {old} -> {new}")
    for c in d.novi_rep_changes:
        def _s(r):
            if r is None:
                return "None"
            return (f"mode={r['mode']} n={r['n']} low_n={r['low_n']} "
                    f"sticks={sorted(r['stick_ids'])}")
        lines.append(f"    rep  {c.name}: {_s(c.old)} -> {_s(c.new)}")

    n_b, n_s = len(d.overrides_before), len(d.overrides_sent)
    lines.append(f"  category overrides: {n_b} persisted -> {n_s} re-sent")
    if d.overrides_lost:
        lines.append("  *** OVERRIDE LOSS - a re-save would NOT honor these "
                     "persisted overrides: "
                     + ", ".join(f"{n} (saved {c})"
                                 for n, c in sorted(d.overrides_lost.items()))
                     + " ***")
    if d.overrides_pruned:
        lines.append("  *** OVERRIDES PRUNED - the overridden well is no longer a "
                     "planned well in the recomputed plan: "
                     + ", ".join(f"{n} (saved {c})"
                                 for n, c in sorted(d.overrides_pruned.items()))
                     + " ***")
    return "\n".join(lines)


def render_footer(diffs: list[ScenarioDiff], applied: list[str], apply_mode: bool) -> str:
    changed = [d for d in diffs if d.material]
    errors = [d for d in diffs if d.error]
    clean = [d for d in diffs if not d.material and not d.error]
    lines = ["=" * 78,
             f"TOTAL: {len(diffs)} scenarios - {len(changed)} changed, "
             f"{len(clean)} unchanged, {len(errors)} skipped/errored"]
    if changed:
        lines.append("")
        lines.append("anduin re-pin list: a re-save bumps narvi.scenario.updated_at, so any")
        lines.append("pinned anduin blueox drop config referencing these scenarios will show")
        lines.append("a stale badge and needs a re-pin after the re-save:")
        for d in changed:
            lines.append(f"  - {d.deal_id}/{d.scenario_id}"
                         + (f" ({d.name})" if d.name else ""))
    if apply_mode:
        lines.append("")
        lines.append(f"APPLIED re-saves: {len(applied)}"
                     + (" - " + ", ".join(applied) if applied else ""))
    else:
        lines.append("")
        lines.append("DRY-RUN - nothing was written. Re-run with --apply to re-save the")
        lines.append("changed scenarios through the normal save endpoints.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _fetch_aoi_geojson(conn: psycopg.Connection, deal_id: str, scenario_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_AsGeoJSON(aoi_geom) FROM narvi.scenario "
            "WHERE deal_id = %s AND scenario_id = %s",
            (deal_id, scenario_id))
        row = cur.fetchone()
    return json.loads(row[0]) if row and row[0] else None


def process_scenario(conn: psycopg.Connection, deal_id: str, scenario_id: str,
                     read_only: bool = True) -> ScenarioDiff:
    """Load one persisted scenario, recompute it through the endpoint prepare
    path, and diff. Read-only: in dry-run the whole computation runs inside a
    READ ONLY transaction that is rolled back."""
    conn.rollback()   # fresh transaction per scenario - no residue (load-as-reset)
    if read_only:
        # per-transaction GUC (survives the 6543 transaction pooler, unlike a
        # session-level SET): belt-and-suspenders that dry-run cannot write.
        conn.execute("SET TRANSACTION READ ONLY")
    header, stored_wells = persist.load_scenario(conn, deal_id, scenario_id)
    if header is None:
        return ScenarioDiff(deal_id=deal_id, scenario_id=scenario_id, name=None,
                            mode="unknown", updated_at="",
                            error="scenario not found")
    aoi = _fetch_aoi_geojson(conn, deal_id, scenario_id)
    req, mode, reason = rebuild_request(header, aoi)
    base = dict(deal_id=deal_id, scenario_id=scenario_id,
                name=header.get("name"), mode=mode,
                updated_at=str(header.get("updated_at") or ""))
    if req is None:
        return ScenarioDiff(**base, error=f"unresavable: {reason}")
    try:
        prepared, pruned, req_used = prepare_with_prune(req, conn)
    except HTTPException as exc:
        return ScenarioDiff(**base, error=f"prepare failed ({exc.status_code}): {exc.detail}")
    except Exception as exc:  # a broken scenario must not sink the whole sweep
        return ScenarioDiff(**base, error=f"prepare failed: {exc!r}")
    finally:
        if read_only:
            conn.rollback()   # discard the read transaction (and the GUC)
    return diff_scenario(header, stored_wells, prepared, mode,
                         sent_overrides=req_used.category_overrides,
                         pruned_overrides=pruned)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m app.resave",
        description="Bulk narvi scenario re-save: dry-run diff by default; "
                    "--apply re-saves changed scenarios through the normal "
                    "save endpoints.")
    ap.add_argument("--deal", help="only this deal_id")
    ap.add_argument("--scenario", help="only this scenario_id (any deal unless --deal)")
    ap.add_argument("--apply", action="store_true",
                    help="re-save scenarios whose diff is material (writes!)")
    args = ap.parse_args(argv)

    conn = get_connection()
    try:
        rows = persist.list_scenarios(conn, args.deal)
        if args.scenario:
            rows = [r for r in rows if r["scenario_id"] == args.scenario]
        print(f"narvi bulk re-save - {'APPLY' if args.apply else 'DRY-RUN'} - "
              f"{len(rows)} persisted scenario(s)")
        print(f"{'deal_id':<24} {'scenario_id':<28} {'name':<28} updated_at")
        for r in rows:
            print(f"{r['deal_id']:<24} {r['scenario_id']:<28} "
                  f"{str(r['name'] or ''):<28} {r['updated_at']}")

        diffs: list[ScenarioDiff] = []
        applied: list[str] = []
        for r in rows:
            d = process_scenario(conn, r["deal_id"], r["scenario_id"],
                                 read_only=True)
            diffs.append(d)
            print()
            print(render_diff(d))

        if args.apply:
            for d in diffs:
                if not d.material:
                    continue
                conn.rollback()
                header, _ = persist.load_scenario(conn, d.deal_id, d.scenario_id)
                aoi = _fetch_aoi_geojson(conn, d.deal_id, d.scenario_id)
                req, _mode, reason = rebuild_request(header, aoi)
                if req is None:
                    print(f"apply skipped {d.deal_id}/{d.scenario_id}: {reason}")
                    continue
                overrides = {k: v for k, v in req.category_overrides.items()
                             if k not in d.overrides_pruned}
                req = req.model_copy(update={"category_overrides": overrides})
                try:
                    # the actual endpoint function - guards and all
                    out = _SAVE[type(req)](req, conn)
                except HTTPException as exc:
                    print(f"apply FAILED {d.deal_id}/{d.scenario_id} "
                          f"({exc.status_code}): {exc.detail}")
                    continue
                applied.append(f"{d.deal_id}/{d.scenario_id}")
                print(f"applied {d.deal_id}/{d.scenario_id}: "
                      f"saved_wells={out.get('saved_wells')}")

        print()
        print(render_footer(diffs, applied, args.apply))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

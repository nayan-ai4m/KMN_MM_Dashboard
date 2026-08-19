"""
fresh_material.py
======================================================================
Mass of fresh (mixer -> noodler -> pre-plodder) material delivered in a
trailing window, attributed at ARRIVAL time (when it reaches the
pre-plodder hopper), not throw time (when the noodler ran).

Ported from the design spec in
Tanush/projects/khamgaon/batch_classification/fresh_material_composition/
docs/fresh_mass_per_minute.md, reimplemented standalone here so this
backend has no dependency on that separate service.

Measured at the SOURCE (noodler hopper drawdown), not the destination
(pre-plodder hopper rise) - the noodler hopper has exactly one inlet
(mixer drops) and one outlet (the noodler), so drawdown is an identity
for mass thrown, not an estimate. See the spec doc for the full
reasoning.
======================================================================
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

import postgres

NOODLER_ON_A = 0.5              # noodler current above this => running
NOODLER_MIN_RUN_S = 20.0        # ignore blips shorter than this
DRAWDOWN_SETTLE_S = 120.0       # noodler hopper settle window after a run stops
BATCH_NOODLER_HOPPER_PCT = 40.0  # one mixer batch raises the noodler hopper ~40 pts
LAG_BASELINE_S = 26.0           # median noodler-throw -> pre-plodder-hopper-arrival lag
LOOKBACK_BUFFER_MIN = 60.0      # extra history fetched before the window to catch
                                 # runs that started earlier (starvation runs, settle)


def _kg_per_noodler_pct() -> float | None:
    batch_kg = float(os.environ.get("BATCH_KG", 0) or 0)
    if batch_kg <= 0:
        return None
    return batch_kg / BATCH_NOODLER_HOPPER_PCT


def _on_runs(series: pd.Series, threshold: float, min_run_s: float) -> list[dict]:
    """Segment a current signal into ON runs, chronological order. The
    trailing run is flagged ongoing=True (still running as of the last
    sample) and is kept even if shorter than min_run_s, since it may still
    grow past the debounce floor."""
    s = series.dropna()
    if s.empty:
        return []
    on = s > threshold
    grp = (on != on.shift()).cumsum()

    segs = []
    for _, idx in s.groupby(grp).groups.items():
        segs.append((bool(on.loc[idx[0]]), idx[0], idx[-1]))

    last_ts = s.index[-1]
    out = []
    for state, a, b in segs:
        if not state:
            continue
        dur = (b - a).total_seconds()
        ongoing = b == last_ts
        if not ongoing and dur < min_run_s:
            continue
        out.append(dict(start=a, end=b, duration_s=dur, ongoing=ongoing))
    return out


def _drawdown_pct(noodler_hopper: pd.Series, start, end) -> float | None:
    before = noodler_hopper.loc[:start].dropna()
    after = noodler_hopper.loc[start: end + pd.Timedelta(seconds=DRAWDOWN_SETTLE_S)].dropna()
    if not len(before) or not len(after):
        return None
    return float(before.iloc[-1] - after.min())


def _is_settled(run: dict, wall_now) -> bool:
    """A completed run's drawdown is only trustworthy once its full settle
    window has actually elapsed - otherwise `_drawdown_pct` searches a
    truncated tail and silently returns an undersized (too-early) minimum,
    understating the true drawdown for a run that ended in the last
    DRAWDOWN_SETTLE_S seconds."""
    return not run["ongoing"] and (run["end"] + pd.Timedelta(seconds=DRAWDOWN_SETTLE_S)) <= wall_now


def _window_overlap_s(start, end, window_start, window_end) -> float:
    return max(0.0, (min(end, window_end) - max(start, window_start)).total_seconds())


async def fresh_mass_kg(minutes: float) -> dict:
    """Total fresh material mass (kg) that ARRIVED at the pre-plodder hopper
    during the `minutes` most recent COMPLETE clock minute(s) - e.g. at
    15:04:15 with minutes=1, this returns the figure for [15:03:00, 15:04:00),
    not "the last 60 seconds from whatever the latest DB row happens to be".
    Anchored on wall-clock time, not on the DB's latest sample timestamp, so
    the window boundary is deterministic and repeatable.

    Contributions are time-weighted across the window boundary so partial
    runs contribute only their overlapping share (mass-conserving, matches
    the per-minute allocation in the design spec generalised to a single
    window bucket).

    A noodler run's true mass is only known ~DRAWDOWN_SETTLE_S (120s) after
    it ends (the hopper level keeps falling after the motor stops). For a
    run that's still in progress, OR that ended but hasn't finished
    settling yet, there's no trustworthy measured drawdown - instead its
    contribution is PROJECTED as elapsed arrived-running-time x the most
    recent SETTLED run's rate (kg/s), on the premise that the noodler's
    throw rate is a fixed-speed machine property that doesn't change much
    run to run. This projection is replaced by the real measured value once
    that run itself settles - it exists so the target minute doesn't have
    to wait up to 2 extra minutes for settling before it can be reported.

    Returns {"kg": float | None, "calibrated": bool, "live": bool}. kg is
    None when BATCH_KG isn't configured, or when there's no data to compute
    from. live is True when the total includes a projected (not yet
    settled) contribution.
    """
    kg_per_pct = _kg_per_noodler_pct()
    if kg_per_pct is None:
        return dict(kg=None, calibrated=False, live=False)

    wall_now = pd.Timestamp(datetime.now(timezone.utc))
    window_end = wall_now.floor("min")
    window_start = window_end - pd.Timedelta(minutes=minutes)

    fetch_minutes = minutes + LOOKBACK_BUFFER_MIN
    rows = await postgres.fetch(
        "SELECT timestamp, hopper_level FROM mixer "
        "WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC",
        fetch_minutes,
    )
    noodler_rows = await postgres.fetch(
        "SELECT timestamp, current FROM noodler "
        "WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC",
        fetch_minutes,
    )
    if not rows or not noodler_rows:
        return dict(kg=None, calibrated=True, live=False)

    noodler_hopper = pd.Series(
        [float(r["hopper_level"]) if r["hopper_level"] is not None else None for r in rows],
        index=[r["timestamp"] for r in rows],
    )
    noodler_current = pd.Series(
        [float(r["current"]) if r["current"] is not None else None for r in noodler_rows],
        index=[r["timestamp"] for r in noodler_rows],
    )

    lag = pd.Timedelta(seconds=LAG_BASELINE_S)

    total_kg = 0.0
    live = False
    last_settled_rate = None  # kg/s of the most recent SETTLED run seen so far

    for run in _on_runs(noodler_current, NOODLER_ON_A, NOODLER_MIN_RUN_S):
        settled = _is_settled(run, wall_now)

        if not settled:
            if last_settled_rate is None:
                continue  # no prior rate to project from yet (e.g. cold start)
            # material thrown so far (possibly the whole run, if it already
            # ended but hasn't settled), projected at the last settled rate,
            # then shifted forward by the transport lag
            arrival_start = run["start"] + lag
            arrival_end = (wall_now if run["ongoing"] else run["end"]) + lag
            overlap_s = _window_overlap_s(arrival_start, arrival_end, window_start, window_end)
            if overlap_s > 0:
                total_kg += overlap_s * last_settled_rate
                live = True
            continue

        drawdown = _drawdown_pct(noodler_hopper, run["start"], run["end"])
        if drawdown is None or drawdown <= 0:
            # unknown or contaminated by a concurrent mixer drop (§7.2 of the
            # spec) - excluded rather than counted as zero, since the
            # material demonstrably still moved.
            continue

        run_mass_kg = drawdown * kg_per_pct
        rate = run_mass_kg / run["duration_s"]
        last_settled_rate = rate

        # attribute at ARRIVAL time: shift the run window forward by the
        # transport lag before overlapping it with the target minute
        arrival_start = run["start"] + lag
        arrival_end = run["end"] + lag
        overlap_s = _window_overlap_s(arrival_start, arrival_end, window_start, window_end)
        if overlap_s > 0:
            total_kg += overlap_s * rate

    return dict(kg=round(total_kg, 1), calibrated=True, live=live)

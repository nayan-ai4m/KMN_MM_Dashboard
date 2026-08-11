"""
mixer_classify.py
======================================================================
Batch-hardness classification pipeline for the twin-blade mixer.

Design (per team decision):
  1. find_runs        : find every continuous current-above-threshold run
  2. classify_runs     : label each run "drop" (hopper level rises after it
                         settles) or "mixing" (hopper flat/falling) using the
                         same settle-point logic as pg_mixer_analysis.py
  3. extract_features  : per-phase current features for the MIXING runs only
                         (drop runs are excluded entirely, not merged in)
  4. fit_classifier     : hardness = mean z-score of 6 "load" features.
                         ANOMALY = any single feature more than
                         cfg.anomaly_z_thresh std-devs from the mean (a true
                         outlier, not just "below-average"). Everything else
                         is split HARD/SOFT at the median hardness of the
                         non-anomalous batches. No clustering involved.
  5. score_features     : same rule, applied to one live batch

Shared by:
  - fit_mixer_model.py  (offline: fits + persists the model)
  - main.py /api/mixer/batch-type  (online: scores the most recently completed mixing batch)

Note: the plant's telemetry switched from current_left/current_right to
drive1_current/drive2_current for the same two blade motors around
2026-08-06. Callers should query with:
    COALESCE(current_left, drive1_current) AS current_left,
    COALESCE(current_right, drive2_current) AS current_right
so the full history reads as one continuous signal.
======================================================================
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Config:
    current_clip: float = 100.0     # A, physical ceiling; negatives -> 0
    run_threshold: float = 3.0      # A (max of L,R, smoothed) => mixer running
    smooth_run: int = 5             # samples, median smoothing for run detection
    merge_gap_s: float = 45.0       # merge runs separated by < this many seconds (blade coast/pause)
    min_run_s: float = 60.0         # a "run" must be at least this long to be considered at all
    full_batch_s: float = 480.0     # a "mixing" run must be at least this long to be scored
    active_floor: float = 1.0       # A, samples above this count as "active"
    phase_search: tuple = (0.30, 0.72)  # window to hunt the A|B trough
    smooth_profile: int = 15        # samples, smoothing for trough detection
    hardness_feats: tuple = (
        "plateau", "mean_active", "energy", "B_plat", "peak", "dur_min",
    )
    anomaly_z_thresh: float = 3.0   # a batch is ANOMALY if any hardness feature is this many std-devs off
    # hopper-trend drop-vs-mixing classification (same idea as pg_mixer_analysis.py)
    hopper_trend_eps: float = 3.0   # % rise after settling => a drop happened
    settle_tolerance: float = 0.5   # % - hopper level must hold within this band to count as "settled"
    settle_window: int = 5          # samples that must all sit within settle_tolerance
    settle_max_search_s: float = 600.0  # give up looking for a settle point after this long


def clean_frame(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    df = df.copy()
    for c in ("current_left", "current_right"):
        df[c] = pd.to_numeric(df[c], errors="coerce").clip(lower=0, upper=cfg.current_clip)
    if "hopper_level" in df.columns:
        df["hopper_level"] = pd.to_numeric(df["hopper_level"], errors="coerce")
    df = df.dropna(subset=["current_left", "current_right"]).sort_index()
    df["cmax"] = df[["current_left", "current_right"]].max(axis=1)
    return df


def find_runs(df: pd.DataFrame, cfg: Config):
    """Every continuous current-above-threshold stretch, short pauses merged in,
    with a floor on how short a "run" can be. Not yet classified as drop/mixing."""
    run = df["cmax"].rolling(cfg.smooth_run, center=True, min_periods=1).median() > cfg.run_threshold
    grp = (run != run.shift()).cumsum()

    segs = []
    for _, idx in df.groupby(grp).groups.items():
        if run.loc[idx].iloc[0]:
            segs.append([idx[0], idx[-1]])

    merged = []
    for s, e in segs:
        if merged and (s - merged[-1][1]).total_seconds() < cfg.merge_gap_s:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    return [(s, e) for s, e in merged if (e - s).total_seconds() >= cfg.min_run_s]


def _hopper_at_or_before(df: pd.DataFrame, ts) -> float | None:
    sub = df.loc[:ts, "hopper_level"].dropna()
    return float(sub.iloc[-1]) if len(sub) else None


def _find_settle_point(df: pd.DataFrame, after_ts, cfg: Config):
    """First point after `after_ts` where the hopper level holds flat for
    cfg.settle_window samples within cfg.settle_tolerance - i.e. both the
    drop (if any) and any draining have finished moving it."""
    sub = df.loc[after_ts:, "hopper_level"].dropna()
    n = cfg.settle_window
    for i in range(len(sub) - n + 1):
        window = sub.iloc[i:i + n]
        if (window.index[0] - after_ts).total_seconds() > cfg.settle_max_search_s:
            break
        if window.max() - window.min() <= cfg.settle_tolerance:
            return window.index[0], float(window.iloc[0])
    return None, None


def classify_runs(runs, df: pd.DataFrame, cfg: Config):
    """Label each run "drop" (hopper settles higher than it started) or
    "mixing" (flat/lower) or "" (not enough hopper data to tell). Returns a
    list of dicts, one per run, in the same order as `runs`."""
    out = []
    for s, e in runs:
        hopper_before = _hopper_at_or_before(df, s)
        settle_ts, settle_level = _find_settle_point(df, e, cfg)
        if hopper_before is None or settle_level is None:
            kind = ""
        elif settle_level > hopper_before + cfg.hopper_trend_eps:
            kind = "drop"
        else:
            kind = "mixing"
        out.append(dict(start=s, end=e, kind=kind,
                         hopper_before=hopper_before,
                         settle_ts=settle_ts, hopper_settled_after=settle_level))
    return out


def _phase_stats(x: np.ndarray, floor: float) -> dict:
    x = x[x > floor]
    if x.size == 0:
        return dict(mean=0, peak=0, plat=0, std=0, energy=0, dur=0)
    return dict(mean=x.mean(), peak=x.max(), plat=np.percentile(x, 80),
                std=x.std(), energy=x.sum(), dur=x.size)


def extract_features(df: pd.DataFrame, batches, cfg: Config) -> pd.DataFrame:
    has_hop = "hopper_level" in df.columns
    hop_series = df["hopper_level"] if has_hop else None
    rows = []
    for s, e in batches:
        sub = df.loc[s:e]
        L, R = sub.current_left.values, sub.current_right.values
        C = L + R
        n = len(C)
        if n < 3:
            continue

        sm = pd.Series(C).rolling(cfg.smooth_profile, center=True, min_periods=1).mean().values
        lo, hi = int(n * cfg.phase_search[0]), int(n * cfg.phase_search[1])
        if hi <= lo:
            lo, hi = 0, n
        split = lo + int(np.argmin(sm[lo:hi]))
        A, B = C[:split], C[split:]

        pa, pb = _phase_stats(A, cfg.active_floor), _phase_stats(B, cfg.active_floor)

        ra = A[: max(5, len(A) // 4)]
        slope_a = np.polyfit(np.arange(len(ra)), ra, 1)[0] if len(ra) > 3 else 0.0
        tb = B[-max(5, len(B) // 4):]
        decay_b = np.polyfit(np.arange(len(tb)), tb, 1)[0] if len(tb) > 3 else 0.0

        Ca = C[C > cfg.active_floor]
        row = dict(
            start=s, dur_min=n / 60.0,
            peak=C.max(),
            mean_active=Ca.mean() if Ca.size else 0.0,
            plateau=np.percentile(Ca, 80) if Ca.size else 0.0,
            energy=C.sum(),
            LR_bal=L.sum() / (R.sum() + 1e-9),
            ripple=Ca.std() if Ca.size else 0.0,
            A_mean=pa["mean"], A_peak=pa["peak"], A_dur=pa["dur"] / 60.0,
            A_slope=slope_a, A_energy=pa["energy"],
            B_mean=pb["mean"], B_peak=pb["peak"], B_plat=pb["plat"],
            B_dur=pb["dur"] / 60.0, B_decay=decay_b, B_energy=pb["energy"],
            B_over_A=pb["mean"] / (pa["mean"] + 1e-9),
        )
        if has_hop:
            hop = sub.hopper_level.dropna().values
            pre = hop_series[(hop_series.index >= s - pd.Timedelta(seconds=120))
                              & (hop_series.index <= s)].dropna()
            hop_start = pre.max() if len(pre) else (hop[0] if len(hop) else np.nan)
            row["hop_charge"] = max(0.0, hop_start - np.min(hop)) if len(hop) and not np.isnan(hop_start) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def fit_classifier(ft: pd.DataFrame, cfg: Config):
    """Fit the hardness score + HARD/SOFT/ANOMALY rule on a set of completed
    mixing batches. No clustering - ANOMALY is a true statistical outlier
    (any hardness feature more than cfg.anomaly_z_thresh std-devs off), and
    HARD/SOFT is a plain median split of everything else."""
    ft = ft.copy()

    hf = list(cfg.hardness_feats)
    hard_mean, hard_std = ft[hf].mean(), ft[hf].std()
    z = (ft[hf] - hard_mean) / hard_std
    ft["hardness"] = z.mean(axis=1)
    ft["max_abs_z"] = z.abs().max(axis=1)
    ft["hard_rank"] = ft["hardness"].rank(ascending=False).astype(int)

    is_anomaly = ft["max_abs_z"] > cfg.anomaly_z_thresh
    normal = ft.loc[~is_anomaly]
    hard_threshold = float(normal["hardness"].median()) if len(normal) else float(ft["hardness"].median())

    ft["class"] = np.where(
        is_anomaly, "ANOMALY",
        np.where(ft["hardness"] >= hard_threshold, "HARD", "SOFT"),
    )

    model = dict(hard_mean=hard_mean, hard_std=hard_std,
                 anomaly_z_thresh=cfg.anomaly_z_thresh,
                 hard_threshold=hard_threshold, cfg=cfg)
    return ft, model


def score_features(feat_row: dict, model: dict) -> dict:
    """Score one already-extracted feature row (from extract_features) against a fitted model."""
    cfg: Config = model["cfg"]
    hf = list(cfg.hardness_feats)
    zs = {f: (feat_row[f] - model["hard_mean"][f]) / model["hard_std"][f] for f in hf}
    hardness = float(np.mean(list(zs.values())))
    max_abs_z = float(max(abs(v) for v in zs.values()))

    if max_abs_z > model["anomaly_z_thresh"]:
        label = "ANOMALY"
    elif hardness >= model["hard_threshold"]:
        label = "HARD"
    else:
        label = "SOFT"
    return dict(label=label, hardness=round(hardness, 3), max_abs_z=round(max_abs_z, 3))

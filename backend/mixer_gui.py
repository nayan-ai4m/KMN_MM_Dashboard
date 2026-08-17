"""
mixer_gui.py
=======================================================================
PyQt5 GUI for the mixer batch-hardness classifier (the same pipeline
fit_mixer_model.py uses to train models/mixer_hardness_model.pkl).
Pulls batches directly from the Postgres `mixer` table for a chosen
date range and shows:

  - a table of per-batch features + assigned class (SOFT/HARD/ANOMALY)
  - three chart tabs: Energy-vs-Plateau scatter, normalized current-
    profile overlay by class, and a batch-duration timeline

Batches are scored against the persisted production model
(mixer_hardness_model.pkl) - the same mean/std/threshold main.py's live
/api/mixer/batch-type endpoint uses - so a batch's class here always
matches what the live dashboard showed for it. Re-copy the .pkl whenever
fit_mixer_model.py is re-run so this tool stays in sync with production.

This file is fully standalone (DB config + the classification pipeline
are both inlined below) apart from the model file - copy mixer_gui.py
AND mixer_hardness_model.pkl into the same folder on any machine with
PyQt5, matplotlib, pandas, numpy, psycopg2 and joblib installed, and run:
    python3 mixer_gui.py

The .pkl is looked for next to this script first, then in ./models/
next to it (so it also works run in-place inside the repo).

Refresh is manual (button), pulling a rolling lookback window from Postgres.
=======================================================================
"""
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psycopg2

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QHeaderView,
    QCheckBox,
    QProgressBar,
    QDateTimeEdit,
    QFrame,
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

DB_CONFIG = {
    "host": "100.73.112.56",
    "port": 5432,
    "dbname": "hul",
    "user": "postgres",
    "password": "ai4m2026",
}

DEFAULT_LOOKBACK_DAYS = 1
BUCKET_HOURS = 12


# ==========================================================================
# Classification pipeline (inlined from backend/mixer_classify.py so this
# file has no dependency on the rest of the KMN_MM_Dashboard repo)
# ==========================================================================
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
    # hopper-trend drop-vs-mixing classification
    hopper_trend_eps: float = 3.0   # % rise after settling => a drop happened
    settle_tolerance: float = 0.5   # % - hopper level must hold within this band to count as "settled"
    settle_window: int = 5          # samples that must all sit within settle_tolerance
    settle_max_search_s: float = 600.0  # give up looking for a settle point after this long


# mixer_hardness_model.pkl was trained via `from mixer_classify import Config`,
# so joblib pickled its cfg field as a reference to mixer_classify.Config.
# Register a stand-in module so it unpickles here even without that file.
if "mixer_classify" not in sys.modules:
    _shim = types.ModuleType("mixer_classify")
    _shim.Config = Config
    sys.modules["mixer_classify"] = _shim


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


# ==========================================================================
# Batch DROP / MIXING / ANOMALY event classifier - independently derived
# and validated against a full week of drive1_current + noodler
# hopper_level data (see backend/mixer_batch_tui.py for the derivation and
# a standalone CLI version of this same logic). This answers a different
# question than the hardness pipeline above: not "how good was this
# mixing batch" but "was the motor dropping material, mixing, or firing
# without moving material (anomaly)" - purely from drive1_current shape
# (current_left, after the COALESCE in fetch_mixer_bucket), corroborated
# by hopper_level.
# ==========================================================================
EVENT_ON_THRESHOLD_A = 15.0        # current above this = motor running
EVENT_DROP_MAX_S = 350.0           # runs shorter than this = drop candidate; longer = mixing
EVENT_MIN_ON_S = 15.0              # fold on-blips shorter than this back into OFF (debounce)
EVENT_MIN_RUN_S = 10.0             # ignore degenerate runs shorter than this
EVENT_HOP_RISE_MIN_CONFIRM = 10.0  # min hopper rise within segment to confirm a real DROP

EVENT_LABEL_COLORS = {
    "DROP": "#2e7d32",
    "MIX": "#1565c0",
    "ANOMALY": "#e65100",
}

EVENTS_TABLE_COLUMNS = [
    "start", "end", "label", "duration_s", "current_median",
    "hopper_start", "hopper_end", "hopper_rise",
]


def classify_batch_events(df: pd.DataFrame) -> list[dict]:
    """Segment current_left into OFF / DROP / MIX / ANOMALY events.

    hopper_rise = max(hopper_level) - hopper_level at segment start (not
    end-minus-start: a concurrent noodler cycle can consume material
    mid-segment and erase a net delta even when a real drop happened).
    Across a full week, drop-current-band bursts (19-26A) split cleanly on
    this signal: a cluster near zero rise (no material moved -> ANOMALY)
    and a second cluster from ~12 upward (confirmed DROP), with almost
    nothing in between. Duration alone does NOT separate them - anomaly
    and real-drop durations overlap heavily (5-135s vs 25-260s).
    """
    if df.empty or "current_left" not in df.columns:
        return []

    idx = df.index
    cur = df["current_left"].to_numpy()
    hop = (
        df["hopper_level"].to_numpy()
        if "hopper_level" in df.columns
        else np.full(len(df), np.nan)
    )
    state = cur > EVENT_ON_THRESHOLD_A

    raw_runs = []
    start_i, run_state = 0, state[0]
    for i in range(1, len(state)):
        if state[i] != run_state:
            raw_runs.append((run_state, start_i, i - 1))
            run_state, start_i = state[i], i
    raw_runs.append((run_state, start_i, len(state) - 1))

    merged = []
    for s, a, b in raw_runs:
        dur = (idx[b] - idx[a]).total_seconds()
        if s and dur < EVENT_MIN_ON_S:
            s = False
        if merged and merged[-1][0] == s:
            merged[-1] = (s, merged[-1][1], b)
        else:
            merged.append([s, a, b])

    # the trailing run may just be cut off by the query window rather than
    # actually finished - drop it so it never gets mislabeled ANOMALY for
    # not having had time to show a hopper rise, or MIX for looking "long"
    # only because the window ended.
    if merged and merged[-1][0] and merged[-1][2] == len(state) - 1:
        merged = merged[:-1]

    events = []
    for s, a, b in merged:
        t0, t1 = idx[a], idx[b]
        dur = (t1 - t0).total_seconds()
        if dur < EVENT_MIN_RUN_S:
            continue
        currents = cur[a : b + 1]
        hoppers = hop[a : b + 1]
        valid = hoppers[~np.isnan(hoppers)]
        hop_start = float(valid[0]) if len(valid) else None
        hop_end = float(valid[-1]) if len(valid) else None
        hop_rise = float(np.nanmax(hoppers) - hop_start) if hop_start is not None else None

        if not s:
            label = "OFF"
        elif dur < EVENT_DROP_MAX_S:
            label = "DROP" if (hop_rise is not None and hop_rise >= EVENT_HOP_RISE_MIN_CONFIRM) else "ANOMALY"
        else:
            label = "MIX"

        events.append(dict(
            label=label, start=t0, end=t1, duration_s=dur,
            current_median=float(np.median(currents)),
            hopper_start=hop_start, hopper_end=hop_end, hopper_rise=hop_rise,
        ))
    return events


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


def score_features(feat_row: dict, model: dict) -> dict:
    """Score one already-extracted feature row against the persisted model -
    identical rule fit_classifier used at training time, just applied with
    fixed (already-fitted) mean/std/threshold instead of re-fitting them."""
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
    return dict(label=label, hardness=hardness, max_abs_z=max_abs_z)


def score_dataframe(ft: pd.DataFrame, model: dict) -> pd.DataFrame:
    """Apply score_features to every batch row. hard_rank is a purely local
    display ordering (by hardness, most-to-least) - it's not part of the
    trained model, just a convenience for eyeballing the table."""
    ft = ft.copy()
    scored = [score_features(row.to_dict(), model) for _, row in ft.iterrows()]
    ft["class"] = [s["label"] for s in scored]
    ft["hardness"] = [s["hardness"] for s in scored]
    ft["max_abs_z"] = [s["max_abs_z"] for s in scored]
    ft["hard_rank"] = ft["hardness"].rank(ascending=False).astype(int)
    return ft


MODEL_FILENAME = "mixer_hardness_model.pkl"


def find_model_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (here / MODEL_FILENAME, here / "models" / MODEL_FILENAME):
        if candidate.is_file():
            return candidate
    return None


def load_model() -> tuple[dict | None, str]:
    """Returns (model, status_message). model is None if it couldn't be loaded."""
    path = find_model_path()
    if path is None:
        return None, (
            f"{MODEL_FILENAME} not found next to this script (or in ./models/). "
            "Copy it alongside mixer_gui.py."
        )
    try:
        model = joblib.load(path)
    except Exception as exc:
        return None, f"Failed to load {path}: {exc}"

    info = f"Model: {path.name}"
    if "fit_at" in model:
        info += f" | fit {model['fit_at']}"
    if "n_train_batches" in model:
        info += f" | trained on {model['n_train_batches']} batches"
    return model, info


CLASS_COLORS = {
    "ANOMALY": "#9aa0a6",
    "SOFT": "#4a90d9",
    "HARD": "#c1272d",
}

TABLE_COLUMNS = [
    "start", "class", "dur_min", "peak", "mean_active", "plateau",
    "energy", "A_mean", "A_peak", "A_slope", "B_mean", "B_peak", "B_decay",
    "B_over_A", "hop_charge", "LR_bal", "hardness", "max_abs_z", "hard_rank",
]


def _bucket_ranges(start: datetime, end: datetime, bucket_hours: int = BUCKET_HOURS):
    ranges = []
    cur = start
    step = timedelta(hours=bucket_hours)
    while cur < end:
        nxt = min(cur + step, end)
        ranges.append((cur, nxt))
        cur = nxt
    return ranges


def fetch_mixer_bucket(conn, start: datetime, end: datetime) -> pd.DataFrame:
    query = """
        SELECT "timestamp",
               COALESCE(current_left, drive1_current) AS current_left,
               COALESCE(current_right, drive2_current) AS current_right,
               hopper_level
        FROM mixer
        WHERE "timestamp" >= %s AND "timestamp" < %s
        ORDER BY "timestamp"
    """
    return pd.read_sql(query, conn, params=(start, end))


def _prep(raw: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """timestamp -> tz-naive IST index, then run the shared clean_frame."""
    raw = raw.rename(columns=str.strip)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="coerce")
    raw["timestamp"] = raw["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    raw = raw.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    return clean_frame(raw, cfg)


def _full_mixing_batches(df: pd.DataFrame, cfg: Config):
    """Full-length mixing batches, found via the current+hopper-validated
    DROP/MIX/ANOMALY event classifier (classify_batch_events) rather than
    the old 3A-threshold/45s-merge/hopper-settle-point logic, which was
    swallowing the ~30-45s inter-cycle pauses and fusing whole sequences
    of cycles into one giant "run" (see backend/mixer_batch_tui.py for the
    derivation). classify_batch_events already drops a trailing run that
    might just be cut off by the query boundary, so no separate check is
    needed here. cfg is accepted for interface compatibility but unused -
    the event classifier's own thresholds are what's validated."""
    events = classify_batch_events(df)
    return [
        dict(start=e["start"], end=e["end"], kind="mixing")
        for e in events if e["label"] == "MIX"
    ]


def fetch_batch_count(start: datetime, end: datetime, cfg: Config) -> int:
    """Lightweight count-only query, used for the 'today' stat card."""
    with psycopg2.connect(**DB_CONFIG) as conn:
        raw = fetch_mixer_bucket(conn, start, end)
    if raw.empty:
        return 0
    df = _prep(raw, cfg)
    return len(_full_mixing_batches(df, cfg))


class FetchWorker(QThread):
    """Fetches the mixer table in bucketed windows and runs the
    classification pipeline, all off the GUI thread."""

    progress = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_ok = pyqtSignal(object, object, object, object)  # df, batches, ft, events

    def __init__(self, range_start: datetime, range_end: datetime, model: dict):
        super().__init__()
        self.range_start = range_start
        self.range_end = range_end
        self.model = model
        self.cfg = model["cfg"]

    def run(self):
        ranges = _bucket_ranges(self.range_start, self.range_end)
        chunks = []
        try:
            conn = psycopg2.connect(**DB_CONFIG)
        except Exception as exc:
            self.error.emit(f"DB connect error: {exc}")
            return

        try:
            for i, (s, e) in enumerate(ranges, start=1):
                self.progress.emit(
                    f"Fetching bucket {i}/{len(ranges)} "
                    f"({s.strftime('%m-%d %H:%M')} → {e.strftime('%m-%d %H:%M')})..."
                )
                chunk = fetch_mixer_bucket(conn, s, e)
                if not chunk.empty:
                    chunks.append(chunk)
        except Exception as exc:
            self.error.emit(f"DB query error: {exc}")
            return
        finally:
            conn.close()

        if not chunks:
            self.finished_ok.emit(pd.DataFrame(), [], None, [])
            return

        raw = pd.concat(chunks, ignore_index=True)

        self.progress.emit("Cleaning, finding runs, classifying drop vs mixing...")
        try:
            df = _prep(raw, self.cfg)
            events = classify_batch_events(df)
            batches = _full_mixing_batches(df, self.cfg)
            if not batches:
                self.finished_ok.emit(df, [], None, events)
                return

            self.progress.emit(f"Extracting features for {len(batches)} batches...")
            pairs = [(r["start"], r["end"]) for r in batches]
            ft = extract_features(df, pairs, self.cfg)
            ft = score_dataframe(ft, self.model)
            ft = ft.sort_values("start").reset_index(drop=True)
        except Exception as exc:
            self.error.emit(f"Processing error: {exc}")
            return

        self.finished_ok.emit(df, batches, ft, events)


class TodayCountWorker(QThread):
    """Counts full-length mixing batches from today 00:00 to now, off the GUI thread."""

    done = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def run(self):
        now = datetime.now()
        midnight = datetime(now.year, now.month, now.day)
        try:
            count = fetch_batch_count(midnight, now, self.cfg)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.done.emit(count)


class MixerPage(QWidget):
    def __init__(self):
        super().__init__()

        self.model, model_status = load_model()
        self.cfg = self.model["cfg"] if self.model is not None else Config()
        self.df = None            # cleaned raw current data (for profile plots)
        self.batches = None       # [(start, end), ...] aligned to self.ft row order
        self.ft = None            # features + class dataframe
        self.events = None        # DROP/MIX/ANOMALY events (independent of hardness pipeline)
        self.worker = None
        self.today_worker = None

        layout = QVBoxLayout(self)

        model_lbl = QLabel(model_status)
        model_lbl.setStyleSheet(
            "color: #a00;" if self.model is None else "color: #666; font-size: 11px;"
        )
        layout.addWidget(model_lbl)

        controls = QHBoxLayout()
        now = QDateTime.currentDateTime()

        controls.addWidget(QLabel("Start:"))
        self.start_edit = QDateTimeEdit(now.addDays(-DEFAULT_LOOKBACK_DAYS))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        controls.addWidget(self.start_edit)

        controls.addWidget(QLabel("End:"))
        self.end_edit = QDateTimeEdit(now)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        controls.addWidget(self.end_edit)

        self.end_now_chk = QCheckBox("End = now")
        self.end_now_chk.setChecked(True)
        self.end_now_chk.stateChanged.connect(
            lambda state: self.end_edit.setEnabled(not state)
        )
        self.end_edit.setEnabled(False)
        controls.addWidget(self.end_now_chk)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload_data)
        controls.addWidget(self.refresh_btn)

        self.analyse_today_btn = QPushButton("Analyse Today")
        self.analyse_today_btn.clicked.connect(self.analyse_today)
        controls.addWidget(self.analyse_today_btn)

        controls.addStretch()
        self.status_label = QLabel("")
        controls.addWidget(self.status_label)
        layout.addLayout(controls)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        cards = QHBoxLayout()
        self.count_card = self._make_stat_card("Batches in range", "—")
        self.anomaly_card = self._make_stat_card("Anomalies in range", "—")
        self.avg_dur_card = self._make_stat_card("Avg batch duration", "—")
        self.today_card = self._make_stat_card("Batches today (12am–now)", "—")
        cards.addWidget(self.count_card)
        cards.addWidget(self.anomaly_card)
        cards.addWidget(self.avg_dur_card)
        cards.addWidget(self.today_card)
        layout.addLayout(cards)

        self.table = QTableWidget()
        self.table.setColumnCount(len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [c.replace("_", " ").title() for c in TABLE_COLUMNS]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, stretch=2)

        self.tabs = QTabWidget()
        self.scatter_fig = Figure(figsize=(7, 5))
        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        self.tabs.addTab(self.scatter_canvas, "Energy vs Plateau (scatter)")

        self.profile_fig = Figure(figsize=(7, 5))
        self.profile_canvas = FigureCanvas(self.profile_fig)
        self.tabs.addTab(self.profile_canvas, "Current profile by class")

        self.duration_fig = Figure(figsize=(7, 5))
        self.duration_canvas = FigureCanvas(self.duration_fig)
        self.tabs.addTab(self.duration_canvas, "Batch duration timeline")

        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)

        event_cards = QHBoxLayout()
        self.drop_card = self._make_stat_card("Batches dropped", "—")
        self.mix_card = self._make_stat_card("Batches mixed", "—")
        self.event_anomaly_card = self._make_stat_card(
            "Unconfirmed (current fired, no material moved)", "—"
        )
        event_cards.addWidget(self.drop_card)
        event_cards.addWidget(self.mix_card)
        event_cards.addWidget(self.event_anomaly_card)
        events_layout.addLayout(event_cards)

        self.events_table = QTableWidget()
        self.events_table.setColumnCount(len(EVENTS_TABLE_COLUMNS))
        self.events_table.setHorizontalHeaderLabels(
            [c.replace("_", " ").title() for c in EVENTS_TABLE_COLUMNS]
        )
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.events_table.setSortingEnabled(True)
        events_layout.addWidget(self.events_table)

        self.tabs.addTab(events_tab, "Batch Events (Drop/Mix)")

        layout.addWidget(self.tabs, stretch=3)

        if self.model is None:
            self.refresh_btn.setEnabled(False)
            self.analyse_today_btn.setEnabled(False)
            self.status_label.setText("No model loaded - fix the issue above, then restart.")
        else:
            self.analyse_today()

    def analyse_today(self):
        """Set the range to today 12am -> now and load it."""
        now = QDateTime.currentDateTime()
        midnight = QDateTime(now.date())
        self.start_edit.setDateTime(midnight)
        self.end_now_chk.setChecked(True)
        self.end_edit.setDateTime(now)
        self.reload_data()

    def _make_stat_card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: #f5f5f5; border-radius: 8px; padding: 6px; }"
        )
        v = QVBoxLayout(card)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #666; font-size: 11px;")
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet("font-size: 22px; font-weight: bold;")
        v.addWidget(title_lbl)
        v.addWidget(value_lbl)
        card.value_label = value_lbl  # stash for later updates
        return card

    def _refresh_today_card(self):
        if self.today_worker is not None and self.today_worker.isRunning():
            return
        self.today_worker = TodayCountWorker(self.cfg)
        self.today_worker.done.connect(
            lambda n: self.today_card.value_label.setText(str(n))
        )
        self.today_worker.error.connect(
            lambda msg: self.today_card.value_label.setText("err")
        )
        self.today_worker.start()

    # ------------------------------------------------------------------
    def reload_data(self):
        if self.model is None:
            return
        if self.worker is not None and self.worker.isRunning():
            return  # a refresh is already in flight

        start = self.start_edit.dateTime().toPyDateTime()
        end = (
            datetime.now()
            if self.end_now_chk.isChecked()
            else self.end_edit.dateTime().toPyDateTime()
        )
        if end <= start:
            self.status_label.setText("End must be after start.")
            return

        self.refresh_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting fetch...")

        self.worker = FetchWorker(start, end, self.model)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.error.connect(self._on_fetch_error)
        self.worker.finished_ok.connect(self._on_fetch_done)
        self.worker.start()
        self._refresh_today_card()

    def _on_fetch_error(self, message: str):
        self.refresh_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)

    def _on_fetch_done(self, df, batches, ft, events):
        self.refresh_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        self.df, self.ft = df, ft
        self.events = events
        self._populate_events_table(events)
        self._update_event_stats(events)

        if ft is None or not batches:
            self.status_label.setText("No full-length mixing batches found in the selected range.")
            self.table.setRowCount(0)
            self.batches = []
            self.count_card.value_label.setText("0")
            self.anomaly_card.value_label.setText("0")
            self.avg_dur_card.value_label.setText("—")
            self._clear_plots()
            return

        # keep a batches list aligned to ft's sorted-by-start row order,
        # regardless of any rows extract_features may have skipped
        by_start = {r["start"]: (r["start"], r["end"]) for r in batches}
        self.batches = [by_start[s] for s in ft["start"]]

        self._populate_table(ft)
        self._redraw_plots()

        n_anomaly = int((ft["class"] == "ANOMALY").sum())
        self.count_card.value_label.setText(str(len(ft)))
        self.anomaly_card.value_label.setText(str(n_anomaly))
        self.avg_dur_card.value_label.setText(f"{ft['dur_min'].mean():.1f} min")
        self.status_label.setText(
            f"{len(ft)} full batches | classes: {ft['class'].value_counts().to_dict()}"
        )

    # ------------------------------------------------------------------
    def _populate_table(self, ft: pd.DataFrame):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(ft))
        for row, (_, rec) in enumerate(ft.iterrows()):
            values = [
                rec["start"].strftime("%Y-%m-%d %H:%M"),
                rec["class"],
                f"{rec['dur_min']:.1f}",
                f"{rec['peak']:.1f}",
                f"{rec['mean_active']:.1f}",
                f"{rec['plateau']:.1f}",
                f"{rec['energy']:.0f}",
                f"{rec['A_mean']:.1f}",
                f"{rec['A_peak']:.1f}",
                f"{rec['A_slope']:.3f}",
                f"{rec['B_mean']:.1f}",
                f"{rec['B_peak']:.1f}",
                f"{rec['B_decay']:.3f}",
                f"{rec['B_over_A']:.2f}",
                f"{rec.get('hop_charge', 0):.1f}",
                f"{rec['LR_bal']:.2f}",
                f"{rec['hardness']:.2f}",
                f"{rec['max_abs_z']:.2f}",
                f"{int(rec['hard_rank'])}",
            ]
            color = QColor(CLASS_COLORS.get(rec["class"], "#000000"))
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 1:  # class column
                    item.setForeground(color)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)

    def _populate_events_table(self, events):
        rows = [e for e in (events or []) if e["label"] in ("DROP", "MIX", "ANOMALY")]
        self.events_table.setSortingEnabled(False)
        self.events_table.setRowCount(len(rows))
        for row, e in enumerate(rows):
            values = [
                e["start"].strftime("%Y-%m-%d %H:%M:%S"),
                e["end"].strftime("%Y-%m-%d %H:%M:%S"),
                e["label"],
                f"{e['duration_s']:.0f}",
                f"{e['current_median']:.1f}",
                f"{e['hopper_start']:.1f}" if e["hopper_start"] is not None else "",
                f"{e['hopper_end']:.1f}" if e["hopper_end"] is not None else "",
                f"{e['hopper_rise']:.1f}" if e["hopper_rise"] is not None else "",
            ]
            color = QColor(EVENT_LABEL_COLORS.get(e["label"], "#000000"))
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 2:  # label column
                    item.setForeground(color)
                self.events_table.setItem(row, col, item)
        self.events_table.setSortingEnabled(True)

    def _update_event_stats(self, events):
        if not events:
            self.drop_card.value_label.setText("—")
            self.mix_card.value_label.setText("—")
            self.event_anomaly_card.value_label.setText("—")
            return
        self.drop_card.value_label.setText(str(sum(1 for e in events if e["label"] == "DROP")))
        self.mix_card.value_label.setText(str(sum(1 for e in events if e["label"] == "MIX")))
        self.event_anomaly_card.value_label.setText(str(sum(1 for e in events if e["label"] == "ANOMALY")))

    # ------------------------------------------------------------------
    def _clear_plots(self):
        self.scatter_fig.clear()
        self.scatter_canvas.draw()
        self.profile_fig.clear()
        self.profile_canvas.draw()
        self.duration_fig.clear()
        self.duration_canvas.draw()

    def _redraw_plots(self):
        if self.ft is None or self.ft.empty:
            self._clear_plots()
            return
        self._draw_scatter(self.ft)
        self._draw_profiles(self.ft, self.batches)
        self._draw_duration_bars(self.ft)

    def _draw_scatter(self, ft: pd.DataFrame):
        self.scatter_fig.clear()
        ax = self.scatter_fig.add_subplot(111)
        for lab, color in CLASS_COLORS.items():
            g = ft[ft["class"] == lab]
            if len(g):
                ax.scatter(
                    g["energy"] / 1000, g["plateau"], c=color, s=55,
                    edgecolor="w", label=f"{lab} (n={len(g)})",
                )
        ax.set(
            xlabel="Energy ∫(L+R)dt (kA·s)",
            ylabel="Plateau current (A)",
            title=f"Soft → Hard separation (n={len(ft)} shown)",
        )
        ax.legend()
        ax.grid(alpha=0.2)
        self.scatter_fig.tight_layout()
        self.scatter_canvas.draw()

    def _draw_profiles(self, ft: pd.DataFrame, batches):
        self.profile_fig.clear()
        ax = self.profile_fig.add_subplot(111)

        def norm_prof(s, e, N=100):
            C = (self.df.loc[s:e].current_left + self.df.loc[s:e].current_right).values
            C = pd.Series(C).rolling(15, center=True, min_periods=1).mean().values
            return np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(C)), C)

        profs = np.array([norm_prof(s, e) for s, e in batches])
        ft = ft.reset_index(drop=True)
        for lab, color in CLASS_COLORS.items():
            idx = ft.index[ft["class"] == lab].to_numpy()
            if idx.size:
                ax.plot(
                    np.linspace(0, 100, 100), profs[idx].mean(0),
                    color=color, lw=2.5, label=f"{lab} (n={idx.size})",
                )
        ax.axvspan(0, 55, color="#f0a500", alpha=0.06)
        ax.axvspan(55, 100, color="#7b2ff7", alpha=0.06)
        ax.set(
            xlabel="Batch progress (%)", ylabel="L+R current (A)",
            title=f"Two-phase current signature by class (n={len(ft)} shown)",
        )
        ax.legend()
        ax.grid(alpha=0.2)
        self.profile_fig.tight_layout()
        self.profile_canvas.draw()

    def _draw_duration_bars(self, ft: pd.DataFrame):
        self.duration_fig.clear()
        ax = self.duration_fig.add_subplot(111)

        ft = ft.sort_values("start").reset_index(drop=True)
        colors = [CLASS_COLORS.get(c, "#333333") for c in ft["class"]]
        ax.bar(range(len(ft)), ft["dur_min"], color=colors, edgecolor="white")

        for lab, color in CLASS_COLORS.items():
            if (ft["class"] == lab).any():
                ax.bar(0, 0, color=color, label=lab)  # legend proxy

        step = max(1, len(ft) // 15)
        ax.set_xticks(range(0, len(ft), step))
        ax.set_xticklabels(
            [ft["start"].iloc[i].strftime("%m-%d %H:%M") for i in range(0, len(ft), step)],
            rotation=45, ha="right", fontsize=8,
        )
        ax.set(
            xlabel="Batch (chronological)", ylabel="Duration (min)",
            title=f"Batch duration timeline (n={len(ft)} shown)",
        )
        ax.legend()
        ax.grid(alpha=0.2, axis="y")
        self.duration_fig.tight_layout()
        self.duration_canvas.draw()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KMN Khamgaon — Mixer Hardness Classifier")
        self.resize(1350, 850)
        self.setCentralWidget(MixerPage())


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

"""
fit_mixer_model.py
======================================================================
Offline fitting job for the live mixer batch-hardness classifier.
Pulls the full history from the `mixer` table, finds every run, classifies
each as a drop or a mixing batch, extracts features from the mixing batches,
fits the hardness score + HARD/SOFT/ANOMALY thresholds, and persists it to
models/mixer_hardness_model.pkl for main.py's /api/mixer/batch-type endpoint
to load.

Re-run this periodically (e.g. monthly, or after a sensor/telemetry
change) to keep the model current. It is NOT run automatically by the
API process - fitting over the full history is too slow/heavy to do on
every server start.

Usage:
    .venv/bin/python fit_mixer_model.py
    .venv/bin/python fit_mixer_model.py --start "2026-08-08 00:00:00"   # only train on data from this IST timestamp onward
======================================================================
"""
import argparse
import os
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
import psycopg2
from dotenv import load_dotenv

from mixer_classify import Config, classify_batch_events, clean_frame, extract_features, fit_classifier

load_dotenv()
IST = ZoneInfo("Asia/Kolkata")
MODEL_PATH = Path(__file__).resolve().parent / "models" / "mixer_hardness_model.pkl"
FETCH_CHUNK_DAYS = 3


@contextmanager
def _stage(name: str):
    print(f"==> {name}...", flush=True)
    t0 = time.time()
    yield
    print(f"    done in {time.time() - t0:.1f}s", flush=True)


def _connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def _fetch_chunked(table: str, columns: str, start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Fetch a table's history (optionally from `start` onward) in visible
    day-sized chunks instead of one giant query, so progress is printed live
    instead of going silent."""
    conn = _connect()
    try:
        cur = conn.cursor()
        if start is not None:
            cur.execute(f"SELECT min(timestamp), max(timestamp) FROM {table} WHERE timestamp >= %s", (start,))
        else:
            cur.execute(f"SELECT min(timestamp), max(timestamp) FROM {table}")
        t_min, t_max = cur.fetchone()
        if t_min is None:
            return pd.DataFrame(columns=["timestamp"] + [c.strip() for c in columns.split(",")])
        print(f"  time range: {t_min} -> {t_max}", flush=True)

        step = timedelta(days=FETCH_CHUNK_DAYS)
        bounds = []
        cur_t = t_min
        while cur_t < t_max:
            nxt = min(cur_t + step, t_max)
            bounds.append((cur_t, nxt))
            cur_t = nxt

        frames = []
        n_rows = 0
        t0 = time.time()
        for i, (s, e) in enumerate(bounds, 1):
            cur.execute(
                f"SELECT timestamp, {columns} FROM {table} "
                f"WHERE timestamp >= %s AND timestamp < %s ORDER BY timestamp",
                (s, e),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            frames.append(pd.DataFrame(rows, columns=cols))
            n_rows += len(rows)
            pct = i / len(bounds) * 100
            print(
                f"  [{i}/{len(bounds)}] {pct:5.1f}% | {s.date()} -> {e.date()} "
                f"| +{len(rows):,} rows (total {n_rows:,}) | {time.time() - t0:5.1f}s elapsed",
                flush=True,
            )
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    finally:
        conn.close()
    return df


def fetch_history(start: pd.Timestamp | None = None) -> pd.DataFrame:
    df = _fetch_chunked(
        "mixer",
        "COALESCE(current_left, drive1_current) AS current_left, "
        "COALESCE(current_right, drive2_current) AS current_right, "
        "hopper_level",
        start=start,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST).dt.tz_localize(None)
    return df.set_index("timestamp")


def main():
    parser = argparse.ArgumentParser(description="Fit the mixer batch-hardness model.")
    parser.add_argument(
        "--start", type=str, default=None,
        help="Only train on data from this timestamp onward (IST, e.g. '2026-08-08 00:00:00'). "
             "Default: full history.",
    )
    args = parser.parse_args()
    start = pd.Timestamp(args.start) if args.start else None

    cfg = Config()

    with _stage("[1/4] Fetching mixer history from Postgres"):
        raw = fetch_history(start=start)
    print(f"  {len(raw):,} rows, {raw.index.min()} -> {raw.index.max()}")

    with _stage("[2/4] Cleaning + classifying drop / mixing / anomaly events"):
        df = clean_frame(raw, cfg)
        events = classify_batch_events(df)
        mixing = [dict(start=e["start"], end=e["end"], kind="mixing")
                  for e in events if e["label"] == "MIX"]
        drops = [e for e in events if e["label"] == "DROP"]
        anomalies = [e for e in events if e["label"] == "ANOMALY"]
    print(f"  events: {len(events)} | mixing (full-length): {len(mixing)} "
          f"| drops: {len(drops)} | anomalies: {len(anomalies)}")

    with _stage("[3/4] Extracting per-batch features + fitting hardness model"):
        ft = extract_features(df, [(r["start"], r["end"]) for r in mixing], cfg)
        ft, model = fit_classifier(ft, cfg)

    print(f"\nhard/soft split threshold (median hardness of non-anomalous batches): {model['hard_threshold']:.3f}")
    print("class sizes:", ft["class"].value_counts().to_dict())
    summary = (ft.groupby("class")
                 .agg(n=("dur_min", "size"), dur_min=("dur_min", "mean"),
                      peak=("peak", "mean"), plateau=("plateau", "mean"),
                      energy=("energy", "mean"), hardness=("hardness", "mean"),
                      max_abs_z=("max_abs_z", "mean"))
                 .round(2))
    print("\n", summary)

    model["fit_at"] = pd.Timestamp.now(tz=IST).isoformat()
    model["n_train_batches"] = len(ft)
    model["train_start"] = str(df.index.min())
    model["train_end"] = str(df.index.max())

    with _stage("[4/4] Saving model"):
        MODEL_PATH.parent.mkdir(exist_ok=True)
        joblib.dump(model, MODEL_PATH)
    print(f"\nwrote {MODEL_PATH} (trained on {len(ft)} batches)")


if __name__ == "__main__":
    main()

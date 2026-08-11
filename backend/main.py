from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import mixer_classify as mc
import postgres
from helpers import int_param, respond

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")
MIXER_MODEL_PATH = Path(__file__).resolve().parent / "models" / "mixer_hardness_model.pkl"
_mixer_model_cache = {"model": None, "mtime": None}


def _load_mixer_model():
    if not MIXER_MODEL_PATH.exists():
        return None
    mtime = MIXER_MODEL_PATH.stat().st_mtime
    if _mixer_model_cache["model"] is None or _mixer_model_cache["mtime"] != mtime:
        _mixer_model_cache["model"] = joblib.load(MIXER_MODEL_PATH)
        _mixer_model_cache["mtime"] = mtime
    return _mixer_model_cache["model"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await postgres.get_pool()
    yield
    await postgres.close_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/mixer/recent")
async def mixer_recent(request: Request):
    minutes = int_param(request, "minutes", default=10)
    rows = await postgres.fetch(
        "SELECT timestamp, drive1_current, drive2_current "
        "FROM mixer WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC LIMIT 5000",
        minutes,
    )
    points = [
        {
            "t": r["timestamp"].astimezone(IST).strftime("%H:%M:%S"),
            "Current_50HP": float(r["drive1_current"]) if r["drive1_current"] is not None else None,
            "Current_60HP": float(r["drive2_current"]) if r["drive2_current"] is not None else None,
        }
        for r in rows
        if r["timestamp"] is not None
    ]
    return respond(points)


@app.get("/api/transport/recent")
async def transport_recent(request: Request):
    minutes = int_param(request, "minutes", default=10)
    bucket_sec = 5
    window = "WHERE timestamp >= now() - ($1 * interval '1 minute') ORDER BY timestamp ASC"

    noodler_rows = await postgres.fetch(f"SELECT timestamp, current FROM noodler {window}", minutes)
    conveyor_rows = await postgres.fetch(
        f"SELECT timestamp, output_current FROM noodler_to_mill_conveyor_data {window}", minutes
    )
    trm_rows = await postgres.fetch(f"SELECT timestamp, current FROM mill {window}", minutes)

    noodler_series = postgres.bucket_and_avg(postgres.rows_to_docs(noodler_rows), "current", bucket_sec)
    conveyor_series = postgres.bucket_and_avg(postgres.rows_to_docs(conveyor_rows), "output_current", bucket_sec)
    trm_series = postgres.bucket_and_avg(postgres.rows_to_docs(trm_rows), "current", bucket_sec)

    merged = postgres.merge_series([noodler_series, conveyor_series, trm_series], ["noodler", "conveyor", "trm"])
    points = [
        {
            "t": datetime.fromtimestamp(row["timestamp"] / 1000, tz=timezone.utc).astimezone(IST).strftime("%H:%M:%S"),
            "noodler": row["noodler"],
            "conveyor": row["conveyor"],
            "trm": row["trm"],
        }
        for row in merged
    ]
    return respond(points)


@app.get("/api/mixer/status")
async def mixer_status():
    latest = await postgres.fetchrow(
        "SELECT batch_count_mixer_2, drive1_current, drive2_current "
        "FROM mixer ORDER BY timestamp DESC LIMIT 1"
    )
    if latest is None:
        return respond({"batchCount": None, "running": False})

    c1 = float(latest["drive1_current"] or 0)
    c2 = float(latest["drive2_current"] or 0)
    running = c1 != 0 or c2 != 0
    batch_count = latest["batch_count_mixer_2"]

    return respond(
        {
            "batchCount": int(batch_count) if batch_count is not None else None,
            "running": running,
        }
    )


MIXER_BATCH_TYPE_LOOKBACK_HOURS = 3


@app.get("/api/mixer/batch-type")
async def mixer_batch_type():
    """Hardness classification of the last batch that has actually been
    dropped into the hopper - not just finished mixing. The hardness number
    comes entirely from that batch's mixing run (the drop itself carries no
    signal), but we only surface it once its drop has been confirmed, so the
    badge reflects what's really in the hopper right now."""
    model = _load_mixer_model()
    if model is None:
        return respond({"modelReady": False, "batchType": None, "hardness": None, "batchEndedAt": None})

    cfg = model["cfg"]
    rows = await postgres.fetch(
        "SELECT timestamp, "
        "COALESCE(current_left, drive1_current) AS current_left, "
        "COALESCE(current_right, drive2_current) AS current_right, "
        "hopper_level "
        "FROM mixer WHERE timestamp >= now() - ($1 * interval '1 hour') "
        "ORDER BY timestamp ASC",
        MIXER_BATCH_TYPE_LOOKBACK_HOURS,
    )
    if not rows:
        return respond({"modelReady": True, "batchType": None, "hardness": None, "batchEndedAt": None})

    df = pd.DataFrame([dict(r) for r in rows]).set_index("timestamp")
    df = mc.clean_frame(df, cfg)

    runs = mc.find_runs(df, cfg)
    classified = mc.classify_runs(runs, df, cfg)
    mixing = [r for r in classified if r["kind"] == "mixing"
              and (r["end"] - r["start"]).total_seconds() >= cfg.full_batch_s]
    drops = [r for r in classified if r["kind"] == "drop"]

    # only count a mixing batch once a confirmed drop happened after it -
    # that's the moment its material actually entered the hopper
    dropped = [m for m in mixing if any(d["start"] > m["end"] for d in drops)]
    if not dropped:
        return respond({"modelReady": True, "batchType": None, "hardness": None, "batchEndedAt": None})

    last = dropped[-1]
    feats = mc.extract_features(df, [(last["start"], last["end"])], cfg)
    if feats.empty:
        return respond({"modelReady": True, "batchType": None, "hardness": None, "batchEndedAt": None})

    scored = mc.score_features(feats.iloc[0].to_dict(), model)
    return respond({
        "modelReady": True,
        "batchType": scored["label"],
        "hardness": scored["hardness"],
        "batchEndedAt": last["end"].isoformat(),
    })


@app.get("/api/pre-plodder/recent")
async def pre_plodder_recent(request: Request):
    minutes = int_param(request, "minutes", default=10)
    rows = await postgres.fetch(
        "SELECT timestamp, current FROM pre_plodder "
        "WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC LIMIT 5000",
        minutes,
    )
    points = [
        {
            "t": r["timestamp"].astimezone(IST).strftime("%H:%M:%S"),
            "current": float(r["current"]) if r["current"] is not None else None,
        }
        for r in rows
        if r["timestamp"] is not None
    ]
    return respond(points)


@app.get("/api/pre-plodder/status")
async def pre_plodder_status():
    row = await postgres.fetchrow(
        "SELECT rpm, turbo_inlet_temp, current FROM pre_plodder ORDER BY timestamp DESC LIMIT 1"
    )
    if row is None:
        return respond({"rpm": None, "turboInletTemp": None, "running": False})
    current = float(row["current"] or 0)
    rpm = row["rpm"]
    turbo_inlet_temp = row["turbo_inlet_temp"]
    return respond(
        {
            "rpm": float(rpm) if rpm is not None else None,
            "turboInletTemp": float(turbo_inlet_temp) if turbo_inlet_temp is not None else None,
            "running": current != 0,
        }
    )


@app.get("/api/bsm/lanes")
async def bsm_lanes():
    rows = await postgres.fetch("SELECT lane, status, last_count FROM live_lane_status ORDER BY lane")
    lanes = [
        {
            "lane": r["lane"],
            "status": r["status"],
            "count": int(r["last_count"]) if r["last_count"] is not None else 0,
        }
        for r in rows
    ]
    return respond(lanes)


@app.get("/api/final-plodder/recent")
async def final_plodder_recent(request: Request):
    minutes = int_param(request, "minutes", default=10)
    bucket_sec = 5
    rows = await postgres.fetch(
        "SELECT timestamp, gru_pred_pv_min, gru_pred_pv_max FROM test_pv_estimations_range_cone "
        "WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC LIMIT 5000",
        minutes,
    )
    docs = postgres.rows_to_docs(rows)
    min_series = postgres.bucket_and_avg(docs, "gru_pred_pv_min", bucket_sec)
    max_series = postgres.bucket_and_avg(docs, "gru_pred_pv_max", bucket_sec)
    points = [
        {
            "t": datetime.fromtimestamp(b / 1000, tz=timezone.utc).astimezone(IST).strftime("%H:%M:%S"),
            "range": [min_series[b], max_series[b]],
        }
        for b in sorted(set(min_series) & set(max_series))
    ]
    return respond(points)


@app.get("/api/final-plodder/status")
async def final_plodder_status():
    cone_row = await postgres.fetchrow("SELECT temp, pressure FROM cone ORDER BY timestamp DESC LIMIT 1")
    drive_row = await postgres.fetchrow("SELECT current FROM final_plodder_drive ORDER BY timestamp DESC LIMIT 1")
    cone_temp = cone_row["temp"] if cone_row is not None else None
    cone_pressure = cone_row["pressure"] if cone_row is not None else None
    current = float(drive_row["current"] or 0) if drive_row is not None else 0
    return respond(
        {
            "coneTemp": float(cone_temp) if cone_temp is not None else None,
            "conePressure": float(cone_pressure) if cone_pressure is not None else None,
            "running": current != 0,
        }
    )

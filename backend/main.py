import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import mixer_classify as mc
import postgres
from helpers import int_param, respond, respond_err

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")
MIXER_MODEL_PATH = Path(__file__).resolve().parent / "models" / "mixer_hardness_model.pkl"
_mixer_model_cache = {"model": None, "mtime": None}

BACKEND_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
with open(BACKEND_CONFIG_PATH) as f:
    _backend_cfg = json.load(f)
LONG_TO_SMALL_BAR_RATIO = float(_backend_cfg["long_to_small_bar_ratio"])


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


@app.get("/api/transport/status")
async def transport_status():
    noodler = await postgres.fetchrow("SELECT current FROM noodler ORDER BY timestamp DESC LIMIT 1")
    conveyor = await postgres.fetchrow(
        "SELECT output_current FROM noodler_to_mill_conveyor_data ORDER BY timestamp DESC LIMIT 1"
    )
    trm = await postgres.fetchrow("SELECT current FROM mill ORDER BY timestamp DESC LIMIT 1")

    noodler_current = float(noodler["current"]) if noodler and noodler["current"] is not None else 0
    conveyor_current = float(conveyor["output_current"]) if conveyor and conveyor["output_current"] is not None else 0
    trm_current = float(trm["current"]) if trm and trm["current"] is not None else 0

    running = noodler_current != 0 or conveyor_current != 0 or trm_current != 0
    return respond({"running": running})


@app.get("/api/mixer/status")
async def mixer_status():
    latest = await postgres.fetchrow(
        "SELECT batch_count_mixer_2, drive1_current, drive2_current "
        "FROM mixer ORDER BY timestamp DESC LIMIT 1"
    )
    mix_event = await postgres.fetchrow(
        "SELECT timestamp, batch_num, batch_score FROM mixer_events WHERE event = 'MIX' ORDER BY timestamp DESC LIMIT 1"
    )

    if latest is None:
        return respond(
            {"batchCount": None, "running": False, "mixBatchNum": None, "mixHardness": None, "mixTime": None}
        )

    c1 = float(latest["drive1_current"] or 0)
    c2 = float(latest["drive2_current"] or 0)
    running = c1 != 0 or c2 != 0
    batch_count = latest["batch_count_mixer_2"]

    return respond(
        {
            "batchCount": int(batch_count) if batch_count is not None else None,
            "running": running,
            "mixBatchNum": mix_event["batch_num"] if mix_event else None,
            "mixHardness": float(mix_event["batch_score"]) if mix_event and mix_event["batch_score"] is not None else None,
            "mixTime": mix_event["timestamp"].astimezone(IST).strftime("%H:%M:%S") if mix_event and mix_event["timestamp"] is not None else None,
        }
    )


MIXER_BATCH_TYPE_LOOKBACK_HOURS = 6


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


@app.get("/api/mixer/drops/recent")
async def mixer_drops_recent(request: Request):
    limit = int_param(request, "limit", default=10)
    rows = await postgres.fetch(
        "SELECT d.timestamp, d.dur, d.kgs_dropped, d.batch_num, d.batch_score, m.timestamp AS mix_timestamp "
        "FROM mixer_events d "
        "LEFT JOIN LATERAL ("
        "  SELECT timestamp FROM mixer_events "
        "  WHERE event = 'MIX' AND batch_num = d.batch_num AND timestamp <= d.timestamp "
        "  ORDER BY timestamp DESC LIMIT 1"
        ") m ON true "
        "WHERE d.event = 'DROP' "
        "ORDER BY d.timestamp DESC LIMIT $1",
        limit,
    )

    def num(value):
        return float(value) if value is not None else None

    points = []
    for r in reversed(rows):
        if r["timestamp"] is None:
            continue
        dur = num(r["dur"])
        age_seconds = None
        if dur is not None and r["mix_timestamp"] is not None:
            drop_end = r["timestamp"] + timedelta(seconds=dur)
            age_seconds = (drop_end - r["mix_timestamp"]).total_seconds()
        points.append(
            {
                "time": r["timestamp"].astimezone(IST).strftime("%H:%M:%S"),
                "batchNum": r["batch_num"],
                "hardness": num(r["batch_score"]),
                "kgsDropped": num(r["kgs_dropped"]),
                "dur": dur,
                "ageSeconds": age_seconds,
            }
        )
    return respond(points)


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


@app.get("/api/recycle/latest")
async def recycle_latest():
    row = await postgres.fetchrow(
        "SELECT timestamp, fringe_mass, recycle_bar_mass, recycle_soap_mass "
        "FROM recycle_material ORDER BY timestamp DESC LIMIT 1"
    )

    if row is None:
        return respond(
            {
                "time": None,
                "fringeMass": None,
                "barMass": None,
                "soapMass": None,
            }
        )

    def num(value):
        return float(value) if value is not None else None

    return respond(
        {
            "time": row["timestamp"].astimezone(IST).strftime("%H:%M") if row["timestamp"] is not None else None,
            "fringeMass": num(row["fringe_mass"]),
            "barMass": num(row["recycle_bar_mass"]),
            "soapMass": num(row["recycle_soap_mass"]),
        }
    )


@app.get("/api/fresh-material/recent")
async def fresh_material_recent(request: Request):
    limit = int_param(request, "limit", default=10)
    rows = await postgres.fetch(
        "SELECT timestamp, dur_ran, kg_added, fresh_material_hardness, batch_no "
        "FROM fresh_material_composition ORDER BY timestamp DESC LIMIT $1",
        limit,
    )

    def num(value):
        return float(value) if value is not None else None

    def fmt(ts):
        return ts.astimezone(IST).strftime("%H:%M:%S") if ts is not None else None

    points = []
    for r in reversed(rows):
        if r["timestamp"] is None:
            continue
        dur_ran = num(r["dur_ran"])
        # timestamp marks when the noodler run STARTED; end = start + dur_ran.
        end_ts = r["timestamp"] + timedelta(seconds=dur_ran) if dur_ran is not None else None
        batch_no = json.loads(r["batch_no"]) if r["batch_no"] is not None else {}
        batches = [
            {"batch": batch, "percent": float(pct)}
            for batch, pct in batch_no.items()
        ]
        points.append(
            {
                "startTime": fmt(r["timestamp"]),
                "endTime": fmt(end_ts),
                "durRan": dur_ran,
                "kgAdded": num(r["kg_added"]),
                "hardness": num(r["fresh_material_hardness"]),
                "batches": batches,
            }
        )
    return respond(points)


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


class SkuPayload(BaseModel):
    skuCode: str
    skuName: str
    productColor: str | None = None
    orificeTopWidthMm: float
    orificeMiddleWidthMm: float
    orificeBottomWidthMm: float
    orificeHeightMm: float
    soapsPerBar: int
    soapWeightG: float
    longBarWeightG: float


class ActiveSkuPayload(BaseModel):
    skuCode: str


def _sku_row_to_json(row) -> dict:
    soap_weight_g = float(row["soap_weight_g"])
    bar_weight_g = float(row["bar_weight_g"])
    soaps_per_bar = row["soaps_per_bar"]
    return {
        "skuCode": row["sku_code"],
        "skuName": row["sku_name"],
        "productColor": row["product_color"],
        "orificeTopWidthMm": float(row["orifice_top_width_mm"]),
        "orificeMiddleWidthMm": float(row["orifice_middle_width_mm"]),
        "orificeBottomWidthMm": float(row["orifice_bottom_width_mm"]),
        "orificeHeightMm": float(row["orifice_height_mm"]),
        "soapsPerBar": soaps_per_bar,
        "soapWeightG": soap_weight_g,
        "longBarWeightG": bar_weight_g,
        "barKg": bar_weight_g * LONG_TO_SMALL_BAR_RATIO / 1000,
        "soapKg": soap_weight_g / 1000,
        "fringeKg": (bar_weight_g - soaps_per_bar * soap_weight_g) / 1000,
    }


@app.get("/api/sku-config")
async def sku_config_get():
    rows = await postgres.fetch("SELECT * FROM sku_config ORDER BY sku_code")
    active_sku = next((r["sku_code"] for r in rows if r["is_active"]), None)
    return respond({"activeSku": active_sku, "skus": [_sku_row_to_json(r) for r in rows]})


@app.post("/api/sku-config/active")
async def sku_config_set_active(payload: ActiveSkuPayload):
    code = payload.skuCode.strip()
    existing = await postgres.fetchrow("SELECT 1 FROM sku_config WHERE sku_code = $1", code)
    if existing is None:
        return respond_err(f"SKU '{code}' not found", status=404)

    pool = await postgres.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE sku_config SET is_active = FALSE WHERE is_active")
            await conn.execute(
                "UPDATE sku_config SET is_active = TRUE, updated_at = now() WHERE sku_code = $1", code
            )
    return respond({"activeSku": code})


@app.post("/api/sku-config/sku")
async def sku_config_save(payload: SkuPayload):
    code = payload.skuCode.strip()
    name = payload.skuName.strip()
    if not code:
        return respond_err("SKU code is required")
    if not name:
        return respond_err("SKU name is required")

    row = await postgres.fetchrow(
        """
        INSERT INTO sku_config (
            sku_code, sku_name, product_color,
            orifice_top_width_mm, orifice_middle_width_mm, orifice_bottom_width_mm, orifice_height_mm,
            soaps_per_bar, soap_weight_g, bar_weight_g
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (sku_code) DO UPDATE SET
            sku_name = EXCLUDED.sku_name,
            product_color = EXCLUDED.product_color,
            orifice_top_width_mm = EXCLUDED.orifice_top_width_mm,
            orifice_middle_width_mm = EXCLUDED.orifice_middle_width_mm,
            orifice_bottom_width_mm = EXCLUDED.orifice_bottom_width_mm,
            orifice_height_mm = EXCLUDED.orifice_height_mm,
            soaps_per_bar = EXCLUDED.soaps_per_bar,
            soap_weight_g = EXCLUDED.soap_weight_g,
            bar_weight_g = EXCLUDED.bar_weight_g,
            updated_at = now()
        RETURNING *
        """,
        code,
        name,
        payload.productColor.strip() if payload.productColor else None,
        payload.orificeTopWidthMm,
        payload.orificeMiddleWidthMm,
        payload.orificeBottomWidthMm,
        payload.orificeHeightMm,
        payload.soapsPerBar,
        payload.soapWeightG,
        payload.longBarWeightG,
    )
    return respond(_sku_row_to_json(row))

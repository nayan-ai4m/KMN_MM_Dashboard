from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import postgres
from helpers import int_param, respond

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")


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
    row = await postgres.fetchrow(
        "SELECT batch_count_mixer_2, drive1_current, drive2_current "
        "FROM mixer ORDER BY timestamp DESC LIMIT 1"
    )
    if row is None:
        return respond({"batchCount": None, "running": False})
    c1 = float(row["drive1_current"] or 0)
    c2 = float(row["drive2_current"] or 0)
    batch_count = row["batch_count_mixer_2"]
    return respond(
        {
            "batchCount": int(batch_count) if batch_count is not None else None,
            "running": c1 != 0 or c2 != 0,
        }
    )


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
    rows = await postgres.fetch(
        "SELECT timestamp, gru_pred_pv_min, gru_pred_pv_max FROM test_pv_estimations_range_cone "
        "WHERE timestamp >= now() - ($1 * interval '1 minute') "
        "ORDER BY timestamp ASC LIMIT 5000",
        minutes,
    )
    points = [
        {
            "t": r["timestamp"].astimezone(IST).strftime("%H:%M:%S"),
            "range": [float(r["gru_pred_pv_min"]), float(r["gru_pred_pv_max"])],
        }
        for r in rows
        if r["timestamp"] is not None and r["gru_pred_pv_min"] is not None and r["gru_pred_pv_max"] is not None
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

import os
import time
from datetime import datetime
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            min_size=1,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(query: str, *args) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args) -> asyncpg.Record | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute(query: str, *args) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_to_ms(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return None


def dt_to_ms(value: Any) -> int | None:
    """Convert an asyncpg-returned timestamptz (datetime) to epoch ms."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    return to_epoch_ms(value)


def to_epoch_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return iso_to_ms(value)
    return None


def rows_to_docs(rows: list[asyncpg.Record], ts_col: str = "timestamp") -> list[dict[str, Any]]:
    """Convert asyncpg rows to plain dicts and add a timestamp_ms field
    derived from `ts_col`, so the existing bucket_and_avg/raw_series/merge_series
    helpers (written against Cosmos's epoch-ms convention) keep working unchanged.
    """
    docs = []
    for r in rows:
        d = dict(r)
        d["timestamp_ms"] = dt_to_ms(d.get(ts_col))
        docs.append(d)
    return docs


def bucket_and_avg(
    docs: list[dict[str, Any]],
    col: str,
    bucket_sec: float,
    ts_col: str = "timestamp_ms",
) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    bucket_ms = bucket_sec * 1000
    for doc in docs:
        val = doc.get(col)
        ts_ms = to_epoch_ms(doc.get(ts_col))
        if val is None or ts_ms is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        b = (ts_ms // bucket_ms) * bucket_ms
        buckets.setdefault(b, []).append(fval)
    return {b: sum(vals) / len(vals) for b, vals in buckets.items()}


def raw_series(
    docs: list[dict[str, Any]], col: str, ts_col: str = "timestamp_ms"
) -> dict[int, float]:
    out: dict[int, float] = {}
    for doc in docs:
        val = doc.get(col)
        ts_ms = to_epoch_ms(doc.get(ts_col))
        if val is None or ts_ms is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        out[ts_ms] = fval
    return out


def merge_series(
    series_list: list[dict[int, float]], keys: list[str]
) -> list[dict[str, Any]]:
    all_buckets: set[int] = set()
    for s in series_list:
        all_buckets.update(s.keys())
    rows = []
    for b in sorted(all_buckets):
        row: dict[str, Any] = {"timestamp": b}
        for i, k in enumerate(keys):
            row[k] = series_list[i].get(b)
        rows.append(row)
    return rows

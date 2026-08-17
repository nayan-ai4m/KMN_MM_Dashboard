"""
Interactive TUI: classify mixer drive1_current into DROP / MIX / ANOMALY
segments over a user-given time range, and report batch counts + durations.

Classification logic (derived empirically from a full week of live data,
212 drop-current-band bursts examined):
  current <= ON_THRESHOLD_A                        -> motor OFF / idle
  current  > ON_THRESHOLD_A, short run (<DROP_MAX_S):
      hopper_rise >= HOP_RISE_MIN_CONFIRM           -> DROPPING (confirmed)
      hopper_rise <  HOP_RISE_MIN_CONFIRM           -> ANOMALY (current fired,
                                                        no material moved)
  current  > ON_THRESHOLD_A, long run (>=DROP_MAX_S) -> MIXING

hopper_rise = max(hopper_level) - hopper_level at segment start (not simply
end-minus-start: a concurrent noodler cycle can consume material mid-segment
and erase a net delta even when a real drop happened). Across a full week,
drop-band bursts split cleanly on this: 22 bursts near-zero rise (0-2), a gap
with almost nothing between 2 and 12, then 188 bursts spread continuously
from 12 upward. Duration does NOT separate these two groups reliably --
anomaly bursts ran 5-135s and real drops ran 25-260s, heavily overlapping.
"""

import os
import statistics
import sys
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

load_dotenv()

ON_THRESHOLD_A = 15.0        # current above this = motor running
DROP_MAX_S = 350             # runs shorter than this = drop candidate; longer = mixing
MIN_RUN_S = 10                # ignore degenerate runs shorter than this (noise)
HOP_RISE_MIN_CONFIRM = 10.0   # min hopper rise within segment to confirm a real DROP


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
    )


def prompt_datetime(label):
    while True:
        raw = input(f"{label} (YYYY-MM-DD HH:MM[:SS]): ").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        print("  Could not parse that. Try again, e.g. 2026-08-12 09:00")


def fetch_rows(conn, start, end):
    query = """
        select date_trunc('minute', timestamp)
                 + (extract(second from timestamp)::int / 5) * interval '5 sec' as t,
               avg(drive1_current) as cur,
               avg(hopper_level) as hopper
        from mixer
        where timestamp between %s and %s
          and drive1_current is not null
        group by 1
        order by 1
    """
    with conn.cursor() as cur:
        cur.execute(query, (start, end))
        rows = cur.fetchall()
    return [(t, float(c), float(h) if h is not None else None) for t, c, h in rows]


def segment(rows):
    if not rows:
        return []

    raw_runs = []
    state = rows[0][1] > ON_THRESHOLD_A
    start_idx = 0
    for i in range(1, len(rows)):
        s = rows[i][1] > ON_THRESHOLD_A
        if s != state:
            raw_runs.append((state, start_idx, i - 1))
            state = s
            start_idx = i
    raw_runs.append((state, start_idx, len(rows) - 1))

    # debounce: fold brief on-blips (<3 samples = 15s) back into surrounding off period
    merged = []
    for s, a, b in raw_runs:
        n = b - a + 1
        if s and n < 3:
            s = False
        if merged and merged[-1][0] == s:
            merged[-1] = (s, merged[-1][1], b)
        else:
            merged.append([s, a, b])

    segments = []
    for s, a, b in merged:
        t0, t1 = rows[a][0], rows[b][0]
        dur = (t1 - t0).total_seconds() + 5
        if dur < MIN_RUN_S:
            continue
        currents = [rows[i][1] for i in range(a, b + 1)]
        hoppers = [rows[i][2] for i in range(a, b + 1) if rows[i][2] is not None]
        hop_rise = (max(hoppers) - hoppers[0]) if hoppers else None
        if not s:
            label = "OFF"
        elif dur < DROP_MAX_S:
            label = "DROP" if (hop_rise is not None and hop_rise >= HOP_RISE_MIN_CONFIRM) else "ANOMALY"
        else:
            label = "MIX"
        segments.append({
            "label": label,
            "start": t0,
            "end": t1,
            "duration_s": dur,
            "current_median": statistics.median(currents),
            "hopper_start": hoppers[0] if hoppers else None,
            "hopper_end": hoppers[-1] if hoppers else None,
            "hopper_delta": (hoppers[-1] - hoppers[0]) if hoppers else None,
            "hopper_rise": hop_rise,
        })
    return segments


def fmt_dur(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def report(segments):
    drops = [s for s in segments if s["label"] == "DROP"]
    mixes = [s for s in segments if s["label"] == "MIX"]
    anomalies = [s for s in segments if s["label"] == "ANOMALY"]

    print("\n" + "=" * 78)
    print(f"BATCHES DROPPED : {len(drops)}")
    print(f"BATCHES MIXED   : {len(mixes)}")
    print(f"ANOMALIES       : {len(anomalies)}  (drop-range current fired, no material moved -- excluded from counts above)")
    print("=" * 78)

    def dur_stats(segs):
        if not segs:
            return "n/a"
        durs = [s["duration_s"] for s in segs]
        return (f"median={fmt_dur(statistics.median(durs))}  "
                f"min={fmt_dur(min(durs))}  max={fmt_dur(max(durs))}")

    print(f"\nDrop duration stats:  {dur_stats(drops)}")
    print(f"Mix duration stats:   {dur_stats(mixes)}")

    print("\n--- DROP events ---")
    if not drops:
        print("  (none)")
    for s in drops:
        print(f"  {s['start'].strftime('%Y-%m-%d %H:%M:%S')} -> {s['end'].strftime('%H:%M:%S')}  "
              f"dur={fmt_dur(s['duration_s']):<8} cur_med={s['current_median']:.1f}A  "
              f"hopper {s['hopper_start']:.1f}->{s['hopper_end']:.1f} "
              f"(rise={s['hopper_rise']:.1f})" if s['hopper_start'] is not None else "")

    print("\n--- MIX events ---")
    if not mixes:
        print("  (none)")
    for s in mixes:
        print(f"  {s['start'].strftime('%Y-%m-%d %H:%M:%S')} -> {s['end'].strftime('%H:%M:%S')}  "
              f"dur={fmt_dur(s['duration_s']):<8} cur_med={s['current_median']:.1f}A  "
              f"hopper {s['hopper_start']:.1f}->{s['hopper_end']:.1f} "
              f"(Δ{s['hopper_delta']:+.1f})" if s['hopper_start'] is not None else "")

    print("\n--- ANOMALY events (not counted as drop or mix) ---")
    if not anomalies:
        print("  (none)")
    for s in anomalies:
        print(f"  {s['start'].strftime('%Y-%m-%d %H:%M:%S')} -> {s['end'].strftime('%H:%M:%S')}  "
              f"dur={fmt_dur(s['duration_s']):<8} cur_med={s['current_median']:.1f}A  "
              f"hopper {s['hopper_start']:.1f}->{s['hopper_end']:.1f} "
              f"(rise={s['hopper_rise']:.1f}, need>={HOP_RISE_MIN_CONFIRM:.0f})" if s['hopper_start'] is not None else "")

    total_off = sum(s["duration_s"] for s in segments if s["label"] == "OFF")
    print(f"\nTotal idle/off time in range: {fmt_dur(total_off)}")
    print("=" * 78 + "\n")


def main():
    print("Mixer batch classifier (drive1_current based)")
    print("-" * 50)
    start = prompt_datetime("Start datetime")
    end = prompt_datetime("End datetime")
    if end <= start:
        print("End must be after start.")
        sys.exit(1)

    print(f"\nQuerying mixer data from {start} to {end} ...")
    conn = get_conn()
    try:
        rows = fetch_rows(conn, start, end)
    finally:
        conn.close()

    if not rows:
        print("No data found in that range.")
        return

    print(f"Fetched {len(rows)} samples (5s resolution).")
    segments = segment(rows)
    report(segments)


if __name__ == "__main__":
    main()

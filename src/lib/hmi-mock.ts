import { useEffect, useRef, useState } from "react";

export type Point = Record<string, number | string | number[] | null>;

/** Deterministic pseudo-random so SSR and first client render agree. */
function seeded(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

const POINTS = 40;

function clock(i: number, total: number) {
  const secondsAgo = (total - 1 - i) * 15;
  const d = new Date(Date.UTC(2026, 0, 1, 8, 0, 0) - secondsAgo * 1000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}:${String(
    d.getUTCSeconds(),
  ).padStart(2, "0")}`;
}

function wave(i: number, base: number, amp: number, freq: number, noise: number, rnd: () => number) {
  return +(base + Math.sin(i * freq) * amp + (rnd() - 0.5) * noise).toFixed(2);
}

export function mixerSeries(): Point[] {
  const rnd = seeded(11);
  return Array.from({ length: POINTS }, (_, i) => ({
    t: clock(i, POINTS),
    motor1: wave(i, 62, 7, 0.35, 3.5, rnd),
    motor2: wave(i, 54, 5.5, 0.28, 3, rnd),
  }));
}

export function transportSeries(): Point[] {
  const rnd = seeded(29);
  return Array.from({ length: POINTS }, (_, i) => ({
    t: clock(i, POINTS),
    noodler: wave(i, 38, 5, 0.4, 2.6, rnd),
    conveyor: wave(i, 16, 2.4, 0.22, 1.4, rnd),
    trm: wave(i, 27, 4, 0.31, 2, rnd),
  }));
}

export function pvPredictionSeries(): Point[] {
  const rnd = seeded(47);
  return Array.from({ length: POINTS }, (_, i) => {
    const actual = wave(i, 82, 3.2, 0.26, 1.6, rnd);
    const isFuture = i >= POINTS - 12;
    return {
      t: clock(i, POINTS),
      actual: isFuture && i > POINTS - 12 ? (null as unknown as number) : actual,
      predicted: i >= POINTS - 13 ? +(actual + Math.sin(i * 0.5) * 1.4).toFixed(2) : (null as unknown as number),
    };
  });
}

export function pvEstimationSeries(): Point[] {
  const rnd = seeded(83);
  return Array.from({ length: POINTS }, (_, i) => {
    const mean = wave(i, 79, 2.8, 0.23, 1.2, rnd);
    const spread = +(1.6 + Math.abs(Math.sin(i * 0.17)) * 2.4).toFixed(2);
    return {
      t: clock(i, POINTS),
      pv: mean,
      range: [+(mean - spread).toFixed(2), +(mean + spread).toFixed(2)],
      band: +(spread * 2).toFixed(2),
    };
  });
}

/** Advances a series by one sample on an interval to make the HMI feel live. */
export function useLiveSeries(initial: Point[], next: (prev: Point, i: number) => Point, ms = 1500) {
  const [data, setData] = useState(initial);
  const tick = useRef(POINTS);

  useEffect(() => {
    const id = setInterval(() => {
      setData((prev) => {
        const last = prev[prev.length - 1]!;
        const point = next(last, tick.current++);
        return [...prev.slice(1), point];
      });
    }, ms);
    return () => clearInterval(id);
  }, [ms, next]);

  return data;
}

export function nowLabel(offsetTicks = 0) {
  const d = new Date(Date.now() + offsetTicks * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(
    d.getSeconds(),
  ).padStart(2, "0")}`;
}

export function drift(value: number, amp: number, min: number, max: number) {
  const v = value + (Math.random() - 0.5) * amp;
  return +Math.min(max, Math.max(min, v)).toFixed(2);
}

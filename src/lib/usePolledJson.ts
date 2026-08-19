import { useEffect, useState } from "react";

// The API runs on the same host as the dashboard, so derive its base URL from
// wherever the page was loaded (plant LAN or Tailscale) instead of baking a
// single IP in at build time. VITE_API_PORT can override the port if needed.
const API_PORT = import.meta.env.VITE_API_PORT ?? "7075";
const API_BASE = `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;

// Abort just under the shortest poll interval so a dead backend can never
// stack up pending requests.
const FETCH_TIMEOUT_MS = 8_000;

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    ...init,
  });
}

async function fetchJson(path: string): Promise<Response> {
  return apiFetch(path);
}

export function usePolledJson<T>(path: string, intervalMs: number, initial: T): T {
  const [data, setData] = useState<T>(initial);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetchJson(path);
        if (!res.ok) return;
        const json = (await res.json()) as T;
        if (!cancelled) setData(json);
      } catch {
        // transient network error; next poll tick retries
      }
    }

    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [path, intervalMs]);

  return data;
}

// Delay in ms until the next wall-clock second-of-minute in `offsetsSec`
// (e.g. [15, 45] => the next :15 or :45 mark), looking into the next minute
// if every offset for the current minute has already passed.
function msUntilNextAlignedTick(offsetsSec: readonly number[]): number {
  const now = Date.now();
  const minuteStart = Math.floor(now / 60_000) * 60_000;
  const candidates = [minuteStart, minuteStart + 60_000].flatMap((base) =>
    offsetsSec.map((s) => base + s * 1000),
  );
  const next = Math.min(...candidates.filter((t) => t > now));
  return next - now;
}

// Like usePolledJson, but fetches at fixed wall-clock seconds-of-minute
// (e.g. offsetsSec=[15, 45] fetches at HH:MM:15 and HH:MM:45) instead of a
// rolling interval timed from mount. Pass a module-level constant array for
// offsetsSec so its identity is stable across renders.
export function usePolledJsonAtSeconds<T>(path: string, offsetsSec: readonly number[], initial: T): T {
  const [data, setData] = useState<T>(initial);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    async function load() {
      try {
        const res = await fetchJson(path);
        if (!res.ok) return;
        const json = (await res.json()) as T;
        if (!cancelled) setData(json);
      } catch {
        // transient network error; next aligned tick retries
      }
    }

    function scheduleNext() {
      timeoutId = setTimeout(async () => {
        await load();
        if (!cancelled) scheduleNext();
      }, msUntilNextAlignedTick(offsetsSec));
    }

    load();
    scheduleNext();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [path, offsetsSec]);

  return data;
}

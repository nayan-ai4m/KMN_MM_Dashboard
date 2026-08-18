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

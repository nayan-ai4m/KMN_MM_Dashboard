import { useEffect, useState } from "react";

const LOCAL_BASE = import.meta.env.VITE_API_BASE_URL_LOCAL ?? "http://localhost:7075";
const TAILSCALE_BASE = import.meta.env.VITE_API_BASE_URL_TAILSCALE ?? LOCAL_BASE;
const CANDIDATE_BASES = [LOCAL_BASE, TAILSCALE_BASE];
const PROBE_TIMEOUT_MS = 2000;

// Shared across all hook instances so a resolved base is reused by every poller,
// and a failure on one path immediately re-probes for the next.
let resolvedBase: string | null = null;

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(id);
  }
}

async function fetchJson(path: string): Promise<Response> {
  const bases = resolvedBase
    ? [resolvedBase, ...CANDIDATE_BASES.filter((base) => base !== resolvedBase)]
    : CANDIDATE_BASES;

  let lastError: unknown;
  for (const base of bases) {
    try {
      const res = await fetchWithTimeout(`${base}${path}`, PROBE_TIMEOUT_MS);
      resolvedBase = base;
      return res;
    } catch (err) {
      lastError = err;
    }
  }
  resolvedBase = null;
  throw lastError;
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

import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL_LOCAL;

async function fetchJson(path: string): Promise<Response> {
  return fetch(`${API_BASE}${path}`);
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

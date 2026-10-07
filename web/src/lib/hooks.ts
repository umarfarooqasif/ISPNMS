import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";

export interface FetchState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads `path` (null = do nothing). Reloads when the path changes, ignores answers that arrive
 * out of order, and can poll while `pollMs(data)` returns a number.
 */
export function useFetch<T>(path: string | null, pollMs?: (data: T | null) => number | null): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  const dataRef = useRef<T | null>(null);

  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const mine = ++seq.current;
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (dataRef.current === null) setLoading(true);

    api<T>(path, { signal: ctrl.signal })
      .then((d) => {
        if (mine !== seq.current) return;
        dataRef.current = d;
        setData(d);
        setError(null);
        const wait = pollMs ? pollMs(d) : null;
        if (wait) timer = setTimeout(() => setTick((t) => t + 1), wait);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current || (e instanceof DOMException && e.name === "AbortError")) return;
        setError(e instanceof ApiError ? e.message : "Something went wrong.");
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });

    return () => {
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
    // pollMs is intentionally not a dependency: it is a plain function of the data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

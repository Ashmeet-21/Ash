"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

/** False during prerender and hydration, true after. Gate UI that reads browser storage. */
export function useHydrated(): boolean {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}

/** Load async data for `deps`; `reload()` fetches again. Ignores results from stale requests. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null; key: string | null }>({ data: null, error: null, key: null });
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([...deps, tick]);

  useEffect(() => {
    let alive = true;
    fn().then(
      (data) => alive && setState({ data, error: null, key }),
      (e: unknown) => alive && setState((s) => ({ data: s.data, error: e instanceof Error ? e.message : String(e), key })),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return {
    data: state.data,
    error: state.error,
    loading: state.key !== key,
    reload: () => setTick((t) => t + 1),
    setData: (d: T) => setState((s) => ({ ...s, data: d })),
  };
}

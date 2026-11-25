"use client";

import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

export interface QueryState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
  setData: (updater: T | null | ((previous: T | null) => T | null)) => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Request failed";
}

/** Minimal data-loading hook: runs `fetcher` on mount / when `deps` change, exposes refresh(). */
export function useQuery<T>(fetcher: () => Promise<T>, deps: DependencyList): QueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  // Always call the latest fetcher, but only re-run when the caller's deps change.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });
  const depsKey = JSON.stringify(deps);

  useEffect(() => {
    let active = true;
    fetcherRef
      .current()
      .then((result) => {
        if (!active) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(errorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [depsKey, version]);

  const refresh = useCallback(() => {
    setLoading(true);
    setVersion((v) => v + 1);
  }, []);

  return { data, error, loading, refresh, setData };
}

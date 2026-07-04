import { useState, useEffect, useRef, useCallback } from "react";
import { get } from "../lib/api";

export function usePolling(url, intervalMs = 30000) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const lastJsonRef = useRef(null);
  const urlRef = useRef(url);

  useEffect(() => {
    if (url !== urlRef.current) {
      urlRef.current = url;
      lastJsonRef.current = null;
    }
  }, [url]);

  const fetchData = useCallback(
    async (signal) => {
      if (!url) return;
      setLoading((current) => (lastJsonRef.current === null ? true : current));
      try {
        const result = await get(url, signal);
        const json = JSON.stringify(result);
        if (json !== lastJsonRef.current) {
          lastJsonRef.current = json;
          setData(result);
        }
        setError(null);
        setLastUpdated(Date.now());
        setLoading(false);
      } catch (err) {
        if (err.name === "AbortError") return;
        setError(err);
        setLoading(false);
      }
    },
    [url]
  );

  const refetch = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const controller = new AbortController();
    const runFetch = () => {
      Promise.resolve().then(() => fetchData(controller.signal));
    };

    runFetch();

    const interval = setInterval(() => {
      runFetch();
    }, intervalMs);

    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [fetchData, intervalMs]);

  return { data, loading, error, lastUpdated, refetch };
}

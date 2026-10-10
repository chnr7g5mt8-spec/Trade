import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

const KEY = 'watchlist:v1';
const DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'KO'];

// Shared in-memory copy so the home and detail screens stay in sync.
let current: string[] | null = null;
const listeners = new Set<(list: string[]) => void>();

async function load(): Promise<string[]> {
  if (current) return current;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    current = raw ? (JSON.parse(raw) as string[]) : DEFAULT_WATCHLIST;
  } catch {
    current = DEFAULT_WATCHLIST;
  }
  return current;
}

function save(list: string[]) {
  current = list;
  listeners.forEach((fn) => fn(list));
  AsyncStorage.setItem(KEY, JSON.stringify(list)).catch(() => {});
}

export function useWatchlist() {
  const [list, setList] = useState<string[]>(current ?? []);
  const [ready, setReady] = useState(current !== null);

  useEffect(() => {
    listeners.add(setList);
    load().then((l) => {
      setList(l);
      setReady(true);
    });
    return () => {
      listeners.delete(setList);
    };
  }, []);

  const add = useCallback((ticker: string) => {
    const list = current ?? [];
    if (!list.includes(ticker)) save([...list, ticker]);
  }, []);

  const remove = useCallback((ticker: string) => {
    save((current ?? []).filter((t) => t !== ticker));
  }, []);

  return { list, ready, add, remove, has: (t: string) => list.includes(t) };
}

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

const KEY = 'watchlist:v1';
const DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'KO', 'BTC-USD'];

// Shared in-memory copy so the home and detail screens stay in sync.
let current: string[] | null = null;
let loading: Promise<string[]> | null = null;
const listeners = new Set<(list: string[]) => void>();

function parse(raw: string | null): string[] {
  if (raw == null) return DEFAULT_WATCHLIST;
  try {
    const value: unknown = JSON.parse(raw);
    if (Array.isArray(value) && value.every((t) => typeof t === 'string')) return value;
  } catch {}
  return DEFAULT_WATCHLIST;
}

function load(): Promise<string[]> {
  if (current) return Promise.resolve(current);
  loading ??= AsyncStorage.getItem(KEY)
    .then(parse, () => DEFAULT_WATCHLIST)
    .then((list) => (current ??= list));
  return loading;
}

async function update(change: (list: string[]) => string[]) {
  // Wait for the stored list first so an early add/remove can't overwrite it,
  // then apply the change to the latest list in case another update landed.
  await load();
  const list = change(current ?? DEFAULT_WATCHLIST);
  current = list;
  listeners.forEach((fn) => fn(list));
  AsyncStorage.setItem(KEY, JSON.stringify(list)).catch(() => {});
}

export function useWatchlist() {
  const [list, setList] = useState<string[]>(current ?? []);
  const [ready, setReady] = useState(current !== null);

  useEffect(() => {
    let mounted = true;
    listeners.add(setList);
    load().then((l) => {
      if (!mounted) return;
      setList(l);
      setReady(true);
    });
    return () => {
      mounted = false;
      listeners.delete(setList);
    };
  }, []);

  const add = useCallback((ticker: string) => {
    update((l) => (l.includes(ticker) ? l : [...l, ticker]));
  }, []);

  const remove = useCallback((ticker: string) => {
    update((l) => l.filter((t) => t !== ticker));
  }, []);

  return { list, ready, add, remove, has: (t: string) => list.includes(t) };
}

/** The current watchlist (for backups). */
export function watchlistSnapshot(): Promise<string[]> {
  return load();
}

/** Replace the whole watchlist (restoring a backup). */
export function replaceWatchlist(list: string[]): Promise<void> {
  return update(() => [...new Set(list.map((t) => t.toUpperCase()))]);
}

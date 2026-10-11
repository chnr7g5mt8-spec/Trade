import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

/**
 * A value saved on this device, shared by every screen that uses it.
 * `parse` turns what was stored back into a value (or the default when it's
 * missing or unreadable).
 */
export function createStore<T>(key: string, fallback: T, parse: (value: unknown) => T | null) {
  let current: T | null = null;
  let loading: Promise<T> | null = null;
  const listeners = new Set<(value: T) => void>();

  function read(raw: string | null): T {
    if (raw == null) return fallback;
    try {
      return parse(JSON.parse(raw)) ?? fallback;
    } catch {
      return fallback;
    }
  }

  function load(): Promise<T> {
    if (current !== null) return Promise.resolve(current);
    loading ??= AsyncStorage.getItem(key)
      .then(read, () => fallback)
      .then((value) => (current ??= value));
    return loading;
  }

  async function update(change: (value: T) => T) {
    // Wait for the stored value first so an early change can't overwrite it.
    await load();
    const value = change(current ?? fallback);
    current = value;
    listeners.forEach((fn) => fn(value));
    AsyncStorage.setItem(key, JSON.stringify(value)).catch(() => {});
  }

  function use() {
    const [value, setValue] = useState<T>(current ?? fallback);
    const [ready, setReady] = useState(current !== null);
    useEffect(() => {
      let mounted = true;
      listeners.add(setValue);
      load().then((v) => {
        if (!mounted) return;
        setValue(v);
        setReady(true);
      });
      return () => {
        mounted = false;
        listeners.delete(setValue);
      };
    }, []);
    const set = useCallback((next: T | ((value: T) => T)) => {
      update(typeof next === 'function' ? (next as (value: T) => T) : () => next);
    }, []);
    return { value, ready, set };
  }

  return { use, load, update, key };
}

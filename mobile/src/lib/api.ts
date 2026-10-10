import Constants from 'expo-constants';
import { Platform } from 'react-native';

export type MetricScore = {
  key: string;
  label: string;
  value: number | null;
  display: string;
  score: number | null;
};

export type CategoryScore = {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  metrics: MetricScore[];
};

export type Rating = {
  ticker: string;
  name: string | null;
  sector: string | null;
  currency: string | null;
  price: number | null;
  score: number | null;
  label: string;
  coverage: number;
  categories: CategoryScore[];
  analyst_target_price: number | null;
  analyst_recommendation: string | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  price_history: number[];
  source: string;
};

/**
 * Backend URL. Set EXPO_PUBLIC_API_URL to override. A production web build
 * is served by the backend itself, so it uses the page's own origin.
 * Otherwise, during development, we assume the API runs on port 8000 of the
 * same machine that serves the Expo bundle, which works for simulators and
 * for phones on the same Wi-Fi network.
 */
function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  if (Platform.OS === 'web' && !__DEV__) return '';
  const host = Constants.expoConfig?.hostUri?.split(':')[0];
  return `http://${host ?? 'localhost'}:8000`;
}

export const API_URL = resolveBaseUrl();

// Same-origin builds have no URL worth showing in error messages.
const SERVER = API_URL ? `the rating server at ${API_URL}` : 'the rating server';
const UNREACHABLE = API_URL
  ? `Can't reach ${SERVER}. Is the backend running?`
  : `Can't reach ${SERVER}. Check your connection and try again.`;

const TIMEOUT_MS = 30_000;

async function getJson<T>(path: string): Promise<T> {
  // The timeout covers the whole exchange, including reading the body.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await request<T>(path, controller.signal);
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error(`${SERVER[0].toUpperCase()}${SERVER.slice(1)} took too long to respond. Try again.`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { signal });
  } catch (e) {
    if (signal.aborted) throw e;
    throw new Error(UNREACHABLE);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function fetchRating(ticker: string): Promise<Rating> {
  return getJson<Rating>(`/api/rating/${encodeURIComponent(ticker)}`);
}

export function fetchRatings(tickers: string[]): Promise<Rating[]> {
  if (tickers.length === 0) return Promise.resolve([]);
  return getJson<Rating[]>(`/api/ratings?tickers=${encodeURIComponent(tickers.join(','))}`);
}

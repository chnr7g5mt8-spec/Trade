import Constants from 'expo-constants';

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
 * Backend URL. Set EXPO_PUBLIC_API_URL to override; otherwise during
 * development we assume the API runs on port 8000 of the same machine that
 * serves the Expo bundle, which works for simulators and for phones on the
 * same Wi-Fi network.
 */
function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const host = Constants.expoConfig?.hostUri?.split(':')[0];
  return `http://${host ?? 'localhost'}:8000`;
}

export const API_URL = resolveBaseUrl();

const TIMEOUT_MS = 30_000;

async function getJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { signal: controller.signal });
  } catch {
    throw new Error(
      controller.signal.aborted
        ? `The rating server at ${API_URL} took too long to respond. Try again.`
        : `Can't reach the rating server at ${API_URL}. Is the backend running?`,
    );
  } finally {
    clearTimeout(timer);
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

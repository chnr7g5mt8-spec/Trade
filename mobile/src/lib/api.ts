import Constants from 'expo-constants';
import { Platform } from 'react-native';

export type MarketState = 'open' | 'pre' | 'post' | 'closed';
export type AssetType = 'stock' | 'fund' | 'crypto';

export type MetricScore = {
  key: string;
  label: string;
  value: number | null;
  display: string;
  score: number | null;
  /** e.g. "Industry median 28.4x" when compared with peers. */
  benchmark: string | null;
};

export type CategoryScore = {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  metrics: MetricScore[];
  /** Only counted when it applies (e.g. dividends for dividend payers). */
  optional: boolean;
};

export type Fact = { label: string; value: string };

export type PeerGroup = { name: string; level: 'industry' | 'sector'; companies: number };

export type Rating = {
  /** Id used in URLs and the watchlist, e.g. "AAPL" or "BTC-USD". */
  ticker: string;
  /** What to show, e.g. "AAPL" or "BTC". */
  symbol: string;
  asset_type: AssetType;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  currency: string | null;
  price: number | null;
  /** Unix seconds of the last regular-session trade. */
  price_time: number | null;
  market_state: MarketState | null;
  /** Pre-market or after-hours price, when there is one. */
  extended_price: number | null;
  extended_session: 'pre' | 'post' | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  price_history: number[];
  score: number | null;
  label: string;
  coverage: number;
  categories: CategoryScore[];
  peer_group: PeerGroup | null;
  facts: Fact[];
  notes: string[];
  source: string;
};

export type SearchResult = {
  ticker: string;
  symbol: string;
  name: string;
  asset_type: AssetType;
  exchange: string | null;
};

export type MethodologyCategory = {
  key: string;
  label: string;
  weight: number;
  optional: boolean;
  metrics: { key: string; label: string; relative: boolean; higher_is_better: boolean }[];
};

export type TrackRecord = {
  generated_at: string;
  universe: string;
  method: string;
  limitations: string[];
  horizon_days: number;
  summary?: {
    test_dates: number;
    observations: number;
    quintile_returns: (number | null)[];
    quintile_median_returns: (number | null)[];
    top_minus_bottom: number | null;
    top_minus_bottom_median: number | null;
    top_beat_bottom_share: number;
    rank_correlation: number | null;
    positive_rank_correlation_share: number;
    independent_years: number;
    average_return: number | null;
    by_label: Record<string, { count: number; average_return: number; median_return: number }>;
    category_rank_correlation: Record<string, number | null>;
    category_positive_share: Record<string, number>;
  };
};

export type Methodology = {
  labels: { label: string; min_score: number }[];
  min_coverage: number;
  relative_weight: number;
  min_peers: number;
  stock_categories: MethodologyCategory[];
  crypto_categories: MethodologyCategory[];
  benchmarks: { generated_at: string | null; industries: number; sectors: number };
  track_record: TrackRecord | null;
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

export function searchAssets(query: string): Promise<SearchResult[]> {
  return getJson<SearchResult[]>(`/api/search?q=${encodeURIComponent(query)}`);
}

export function fetchMethodology(): Promise<Methodology> {
  return getJson<Methodology>('/api/methodology');
}

export type ExploreItem = {
  ticker: string;
  symbol: string;
  name: string;
  score: number;
  label: string;
  category_score: number | null;
  sector: string | null;
  industry: string | null;
  exchange: string | null;
};

export type ExploreList = {
  key: string;
  title: string;
  description: string;
  group: 'featured' | 'sector';
  asset_type: 'stock' | 'crypto';
  category: string | null;
  category_label: string | null;
  items: ExploreItem[];
};

export type Explore = {
  generated_at: string | null;
  universe: string;
  stocks_rated: number;
  coins_rated: number;
  lists: ExploreList[];
};

export function fetchExplore(): Promise<Explore> {
  return getJson<Explore>('/api/explore');
}

import type { Rating } from './api';
import { settingsStore } from './portfolio';
import { createStore } from './store';

/** What was last seen for a ticker, to notice changes. */
type Seen = { label: string; price: number | null; reference: number | null; rate: number | null; currency: string | null };

export type Alert = {
  id: string;
  ticker: string;
  kind: 'rating' | 'dividend' | 'drop';
  message: string;
  /** Unix seconds. */
  at: number;
};

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

export const seenStore = createStore<Record<string, Seen>>('alerts-seen:v1', {}, (v) => (isRecord(v) ? (v as Record<string, Seen>) : null));
export const alertsStore = createStore<Alert[]>('alerts:v1', [], (v) =>
  Array.isArray(v) && v.every((a) => isRecord(a) && typeof a.message === 'string') ? (v as Alert[]) : null,
);

const LABEL_ORDER = ['Strong Sell', 'Sell', 'Hold', 'Buy', 'Strong Buy'];
// A dividend in another listing's currency moves with the exchange rate;
// real cuts are much bigger than that.
const DIVIDEND_CUT = 0.1;
const MAX_ALERTS = 50;

function rateOf(r: Rating): number | null {
  return r.dividend ? r.dividend.amount * r.dividend.per_year : null;
}

/**
 * Alerts for what changed since these tickers were last seen: a rating moving
 * to another label, a dividend cut, or the price falling `dropPct` percent from
 * where it was when first seen (or last alerted). Pure: returns the new state.
 */
export function detect(ratings: Rating[], seen: Record<string, Seen>, dropPct: number, now = Date.now() / 1000) {
  const next = { ...seen };
  const alerts: Alert[] = [];
  const add = (r: Rating, kind: Alert['kind'], message: string) =>
    alerts.push({ id: `${r.ticker}-${kind}-${Math.round(now)}`, ticker: r.ticker, kind, message, at: now });

  for (const r of ratings) {
    const before = seen[r.ticker];
    const rate = rateOf(r);
    if (!before) {
      next[r.ticker] = { label: r.label, price: r.price, reference: r.price, rate, currency: r.dividend?.currency ?? null };
      continue;
    }
    const entry: Seen = { ...before, label: r.label, price: r.price };
    const was = LABEL_ORDER.indexOf(before.label);
    const is = LABEL_ORDER.indexOf(r.label);
    if (was >= 0 && is >= 0 && was !== is)
      add(r, 'rating', `${r.symbol} ${is > was ? 'upgraded' : 'downgraded'} from ${before.label} to ${r.label}${r.score != null ? ` (score ${r.score})` : ''}.`);

    const sameCurrency = (r.dividend?.currency ?? null) === before.currency;
    if (before.rate && rate != null && sameCurrency && rate < before.rate * (1 - DIVIDEND_CUT))
      add(r, 'dividend', `${r.symbol} cut its dividend by ${Math.round((1 - rate / before.rate) * 100)}%.`);
    else if (before.rate && !r.dividend)
      add(r, 'dividend', `${r.symbol} has missed its usual dividend payment.`);
    if (rate != null || !before.rate) {
      entry.rate = rate;
      entry.currency = r.dividend?.currency ?? null;
    }

    if (before.reference && r.price != null && r.price <= before.reference * (1 - dropPct / 100)) {
      add(r, 'drop', `${r.symbol} is down ${Math.round((1 - r.price / before.reference) * 100)}% since you started following it.`);
      entry.reference = r.price; // the next alert needs another drop of the same size
    } else if (before.reference == null) {
      entry.reference = r.price;
    }
    next[r.ticker] = entry;
  }
  return { seen: next, alerts };
}

// Checks run one at a time, so two screens checking at once can't both alert.
let queue: Promise<void> = Promise.resolve();

/** Check ratings for changes and save new alerts (newest first). */
export function checkAlerts(ratings: Rating[], dropPct?: number): Promise<void> {
  queue = queue
    .then(async () => {
      const drop = dropPct ?? (await settingsStore.load()).dropAlert;
      const result = detect(ratings, await seenStore.load(), drop);
      await seenStore.update(() => result.seen);
      if (result.alerts.length) await alertsStore.update((list) => [...result.alerts, ...list].slice(0, MAX_ALERTS));
    })
    .catch(() => {});
  return queue;
}

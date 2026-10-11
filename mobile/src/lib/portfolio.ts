import type { DividendInfo, Rating } from './api';
import { createStore } from './store';

export type Holding = {
  ticker: string;
  shares: number;
  /** Price paid per share, in the listing's currency (null if not entered). */
  cost: number | null;
};

export type BaseCurrency = 'USD' | 'CAD';
export type Settings = { currency: BaseCurrency; dropAlert: number };

const isHolding = (h: unknown): h is Holding =>
  !!h &&
  typeof (h as Holding).ticker === 'string' &&
  typeof (h as Holding).shares === 'number' &&
  (h as Holding).shares > 0 &&
  ((h as Holding).cost === null || typeof (h as Holding).cost === 'number');

export const holdingsStore = createStore<Holding[]>('portfolio:v1', [], (v) =>
  Array.isArray(v) && v.every(isHolding) ? v : null,
);

export const settingsStore = createStore<Settings>('portfolio-settings:v1', { currency: 'USD', dropAlert: 10 }, (v) => {
  const s = v as Settings;
  return s && (s.currency === 'USD' || s.currency === 'CAD') && typeof s.dropAlert === 'number' ? s : null;
});

export function upsertHolding(holding: Holding) {
  return holdingsStore.update((list) => {
    const rest = list.filter((h) => h.ticker !== holding.ticker);
    return [...rest, holding];
  });
}

export function removeHolding(ticker: string) {
  return holdingsStore.update((list) => list.filter((h) => h.ticker !== ticker));
}

// --- money -------------------------------------------------------------------

/** Quote currencies in minor units (pence, cents) and their major currency. */
const MINOR: Record<string, [string, number]> = { GBp: ['GBP', 100], GBX: ['GBP', 100], ZAc: ['ZAR', 100], ILA: ['ILS', 100] };

export function majorCurrency(currency: string | null | undefined): [string, number] {
  if (!currency) return ['USD', 1];
  return MINOR[currency] ?? [currency, 1];
}

export type Rates = Record<string, number | null>;

/** The currency pairs needed to convert every holding into `base`. */
export function neededPairs(ratings: Rating[], base: BaseCurrency): string[] {
  const set = new Set<string>();
  for (const r of ratings) {
    const [major] = majorCurrency(r.currency);
    if (major !== base) set.add(`${major}${base}`);
  }
  return [...set];
}

/** An amount in the listing's currency, in the base currency (null when no rate is known). */
export function convert(amount: number, currency: string | null | undefined, base: BaseCurrency, rates: Rates) {
  const [major, units] = majorCurrency(currency);
  const inMajor = amount / units;
  if (major === base) return inMajor;
  const rate = rates[`${major}${base}`];
  return rate ? inMajor * rate : null;
}

// --- summary -----------------------------------------------------------------

export type Position = {
  holding: Holding;
  rating: Rating | null;
  value: number | null; // base currency
  cost: number | null; // base currency, at today's exchange rate
  gain: number | null;
  income: number | null; // yearly dividends, base currency
  weight: number; // share of the portfolio's value
};

export type Payment = { ticker: string; symbol: string; date: number; amount: number };

export type Summary = {
  positions: Position[];
  value: number;
  cost: number;
  gain: number | null;
  income: number;
  yield: number | null;
  yieldOnCost: number | null;
  score: number | null;
  sectors: { name: string; weight: number }[];
  warnings: string[];
  payments: Payment[]; // expected in the next 12 months
  months: { label: string; amount: number }[]; // next 12 calendar months
  dividendGrowth: number | null; // income-weighted 5-year dividend growth
  missing: string[]; // holdings without a price or rate
};

const YEAR = 365.25 * 86400;

function metric(r: Rating, key: string): number | null {
  for (const c of r.categories) for (const m of c.metrics) if (m.key === key) return m.value;
  return null;
}

/** Ex-dividend dates expected in the next 12 months. */
export function upcoming(d: DividendInfo, now: number): number[] {
  const gap = YEAR / d.per_year;
  const out: number[] = [];
  let t = d.next_ex_date ?? d.last_ex_date + gap;
  while (t < now) t += gap;
  for (; t < now + YEAR; t += gap) out.push(t);
  return out;
}

function bucket(r: Rating): string {
  if (r.asset_type === 'crypto') return 'Crypto';
  if (r.asset_type === 'fund') return 'ETFs & funds';
  return r.sector ?? 'Other';
}

export function summarize(holdings: Holding[], ratings: Rating[], base: BaseCurrency, rates: Rates, now = Date.now() / 1000): Summary {
  const byTicker = new Map(ratings.map((r) => [r.ticker, r]));
  const positions: Position[] = holdings.map((h) => {
    const r = byTicker.get(h.ticker) ?? null;
    const value = r?.price != null ? convert(h.shares * r.price, r.currency, base, rates) : null;
    const cost = r && h.cost != null ? convert(h.shares * h.cost, r.currency, base, rates) : null;
    const d = r?.dividend;
    const income = d ? convert(h.shares * d.amount * d.per_year, d.currency, base, rates) : r ? 0 : null;
    return { holding: h, rating: r, value, cost, gain: value != null && cost != null ? value - cost : null, income, weight: 0 };
  });
  const value = positions.reduce((s, p) => s + (p.value ?? 0), 0);
  for (const p of positions) p.weight = value > 0 && p.value != null ? p.value / value : 0;
  const withCost = positions.filter((p) => p.cost != null && p.value != null);
  const cost = withCost.reduce((s, p) => s + p.cost!, 0);
  const gain = withCost.length ? withCost.reduce((s, p) => s + p.gain!, 0) : null;
  const income = positions.reduce((s, p) => s + (p.income ?? 0), 0);

  const rated = positions.filter((p) => p.rating?.score != null && p.value);
  const ratedValue = rated.reduce((s, p) => s + p.value!, 0);
  const score = ratedValue > 0 ? Math.round(rated.reduce((s, p) => s + p.rating!.score! * p.value!, 0) / ratedValue) : null;

  const sectorTotals = new Map<string, number>();
  for (const p of positions) if (p.rating && p.value) sectorTotals.set(bucket(p.rating), (sectorTotals.get(bucket(p.rating)) ?? 0) + p.value);
  const sectors = [...sectorTotals].map(([name, v]) => ({ name, weight: value ? v / value : 0 })).sort((a, b) => b.weight - a.weight);

  const warnings: string[] = [];
  if (positions.length >= 2) {
    for (const p of positions)
      if (p.weight > 0.25)
        warnings.push(`${p.rating?.symbol ?? p.holding.ticker} is ${Math.round(p.weight * 100)}% of your portfolio. Many investors keep any one holding under 25%.`);
    for (const s of sectors)
      if (s.weight > 0.4 && s.name !== 'ETFs & funds')
        warnings.push(`${s.name} is ${Math.round(s.weight * 100)}% of your portfolio. Spreading across sectors lowers the risk of one industry's slump.`);
  }

  const payments: Payment[] = [];
  for (const p of positions) {
    const d = p.rating?.dividend;
    if (!d || !p.rating) continue;
    const amount = convert(p.holding.shares * d.amount, d.currency, base, rates);
    if (amount == null) continue;
    for (const date of upcoming(d, now)) payments.push({ ticker: p.holding.ticker, symbol: p.rating.symbol, date, amount });
  }
  payments.sort((a, b) => a.date - b.date);

  const start = new Date(now * 1000);
  const months = Array.from({ length: 12 }, (_, i) => {
    const m = new Date(start.getFullYear(), start.getMonth() + i, 1);
    return { key: `${m.getFullYear()}-${m.getMonth()}`, label: m.toLocaleDateString('en-US', { month: 'short' }), amount: 0 };
  });
  for (const pay of payments) {
    const d = new Date(pay.date * 1000);
    const slot = months.find((m) => m.key === `${d.getFullYear()}-${d.getMonth()}`);
    if (slot) slot.amount += pay.amount;
  }

  let growthWeight = 0;
  let growthSum = 0;
  for (const p of positions) {
    const g = p.rating ? metric(p.rating, 'dividend_growth_5y') : null;
    if (g != null && p.income) {
      growthWeight += p.income;
      growthSum += Math.max(-0.2, Math.min(0.2, g)) * p.income;
    }
  }

  return {
    positions,
    value,
    cost,
    gain,
    income,
    yield: value > 0 ? income / value : null,
    yieldOnCost: cost > 0 ? withCost.reduce((s, p) => s + (p.income ?? 0), 0) / cost : null,
    score,
    sectors,
    warnings,
    payments,
    months: months.map(({ label, amount }) => ({ label, amount })),
    dividendGrowth: growthWeight ? growthSum / growthWeight : null,
    missing: positions.filter((p) => p.value == null).map((p) => p.holding.ticker),
  };
}

/**
 * Value and yearly income after `years`, with dividends reinvested or taken as cash.
 * Prices grow by `priceGrowth` a year and dividends per share by `dividendGrowth`.
 */
export function project(value: number, income: number, years: number, priceGrowth: number, dividendGrowth: number, reinvest: boolean) {
  let shares = 1;
  let price = value;
  let dividend = income; // per "share" of the whole portfolio
  let cash = 0;
  for (let y = 0; y < years; y++) {
    const paid = shares * dividend;
    price *= 1 + priceGrowth;
    if (reinvest) shares += paid / price;
    else cash += paid;
    dividend *= 1 + dividendGrowth;
  }
  return { value: shares * price, income: shares * dividend, cash };
}

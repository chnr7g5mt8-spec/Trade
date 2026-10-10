export const colors = {
  bg: '#F5F6F8',
  card: '#FFFFFF',
  text: '#111827',
  muted: '#6B7280',
  border: '#E5E7EB',
  track: '#E5E7EB',
  accent: '#2563EB',
  danger: '#DC2626',
};

/** Red → amber → green scale for 0-100 scores. */
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#9CA3AF';
  if (score >= 80) return '#15803D';
  if (score >= 65) return '#22C55E';
  if (score >= 45) return '#F59E0B';
  if (score >= 30) return '#F97316';
  return '#DC2626';
}

export function formatMoney(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const symbol = !currency || currency === 'USD' ? '$' : '';
  const suffix = symbol ? '' : ` ${currency}`;
  // Sub-dollar prices (penny stocks, many coins) need significant digits, not fixed decimals.
  const amount =
    Math.abs(value) < 1
      ? value.toLocaleString('en-US', { maximumSignificantDigits: 4 })
      : value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${symbol}${amount}${suffix}`;
}

const MARKET_LABELS = {
  open: 'Market open',
  pre: 'Pre-market',
  post: 'After hours',
  closed: 'Market closed',
} as const;

export function marketLabel(state: keyof typeof MARKET_LABELS | null | undefined): string | null {
  return state ? MARKET_LABELS[state] : null;
}

/** e.g. "Oct 9, 4:00 PM" in the viewer's own time zone. */
export function formatTime(unixSeconds: number | null | undefined): string | null {
  if (unixSeconds == null) return null;
  return new Date(unixSeconds * 1000).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function formatChange(from: number, to: number): string {
  const pct = (to / from - 1) * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

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
  if (value == null) return '—';
  const symbol = !currency || currency === 'USD' ? '$' : '';
  const suffix = symbol ? '' : ` ${currency}`;
  return `${symbol}${value.toFixed(2)}${suffix}`;
}

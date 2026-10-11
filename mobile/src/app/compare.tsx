import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { SearchBox } from '../components/SearchBox';
import { fetchRatings, type Rating } from '../lib/api';
import { profileLabel, useProfile } from '../lib/profile';
import { colors, formatMoney, scoreColor } from '../lib/theme';

const MAX = 3;

function parseTickers(raw: string | string[] | undefined): string[] {
  const text = Array.isArray(raw) ? raw.join(',') : (raw ?? '');
  return [...new Set(text.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean))].slice(0, MAX);
}

type Row = { label: string; values: (number | null)[]; texts: string[]; higherIsBetter?: boolean };

function rows(ratings: Rating[]): Row[] {
  const out: Row[] = [];
  const num = (v: number | null | undefined) => (v == null ? null : v);
  out.push({ label: 'Overall score', values: ratings.map((r) => num(r.score)), texts: ratings.map((r) => r.score == null ? '—' : `${r.score} · ${r.label}`) });
  const keys: { key: string; label: string }[] = [];
  for (const r of ratings)
    for (const c of r.categories) if (!keys.some((k) => k.key === c.key)) keys.push({ key: c.key, label: c.label });
  for (const k of keys) {
    const scores = ratings.map((r) => num(r.categories.find((c) => c.key === k.key)?.score));
    out.push({ label: k.label, values: scores, texts: scores.map((s) => (s == null ? '—' : String(Math.round(s)))) });
  }
  if (ratings.some((r) => r.outlook)) {
    const v = ratings.map((r) => num(r.outlook?.score));
    out.push({ label: 'Analyst outlook', values: v, texts: v.map((s) => (s == null ? '—' : String(Math.round(s)))) });
  }
  for (const fact of ['Dividend yield', 'Market cap', 'Fund size', 'Yearly fee']) {
    if (!ratings.some((r) => r.facts.some((f) => f.label === fact))) continue;
    out.push({
      label: fact,
      values: ratings.map(() => null),
      texts: ratings.map((r) => r.facts.find((f) => f.label === fact)?.value ?? '—'),
    });
  }
  return out;
}

/** Two or three stocks, ETFs or coins side by side, category by category. */
export default function Compare() {
  const { tickers: raw } = useLocalSearchParams<{ tickers?: string }>();
  const tickers = parseTickers(raw);
  const key = tickers.join(',');
  const { profile, ready } = useProfile();
  const [data, setData] = useState<{ key: string; ratings: Rating[] } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);

  useEffect(() => {
    if (!ready || !key) return;
    let live = true;
    fetchRatings(key.split(','), profile).then(
      (ratings) => live && setData({ key: `${key}|${profile}`, ratings }),
      (e: Error) => live && setError({ key: `${key}|${profile}`, message: e.message }),
    );
    return () => {
      live = false;
    };
  }, [key, profile, ready]);

  const setTickers = (list: string[]) => router.setParams({ tickers: list.join(',') });
  const current = data?.key === `${key}|${profile}` ? data.ratings : null;
  const failed = error?.key === `${key}|${profile}` ? error.message : null;
  const ratings = current ?? [];

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {tickers.length < MAX && (
        <SearchBox onSelect={(t) => !tickers.includes(t.toUpperCase()) && setTickers([...tickers, t.toUpperCase()])} />
      )}
      <Text style={styles.muted}>
        {tickers.length === 0
          ? 'Search above to add up to three stocks, ETFs or coins to compare.'
          : `Comparing ${tickers.length} of up to ${MAX}. Scores use your investing style: ${profileLabel(profile)}.`}
      </Text>

      {tickers.length > 0 && !current && !failed && <ActivityIndicator style={{ marginTop: 20 }} />}
      {!!failed && <Text style={styles.error}>{failed}</Text>}

      {ratings.length > 0 && (
        <View style={styles.card}>
          <View style={styles.headerRow}>
            {ratings.map((r) => (
              <View key={r.ticker} style={styles.cell}>
                <Pressable
                  onPress={() => router.push({ pathname: '/stock/[ticker]', params: { ticker: r.ticker } })}
                  accessibilityRole="link"
                  accessibilityLabel={`Open ${r.symbol}`}>
                  <Text style={styles.symbol}>{r.symbol}</Text>
                  <Text style={styles.name} numberOfLines={2}>
                    {r.name}
                  </Text>
                  <Text style={styles.price}>{formatMoney(r.price, r.currency)}</Text>
                </Pressable>
                <Pressable
                  onPress={() => setTickers(tickers.filter((t) => t !== r.ticker))}
                  hitSlop={8}
                  accessibilityRole="button"
                  accessibilityLabel={`Remove ${r.symbol}`}>
                  <Text style={styles.remove}>Remove</Text>
                </Pressable>
              </View>
            ))}
          </View>
          {rows(ratings).map((row) => {
            const scored = row.values.filter((v): v is number => v != null);
            const best = scored.length > 1 ? Math.max(...scored) : null;
            return (
              <View key={row.label} style={styles.row} accessibilityLabel={`${row.label}: ${row.texts.join(', ')}`}>
                <Text style={styles.rowLabel}>{row.label}</Text>
                <View style={styles.values}>
                  {row.texts.map((t, i) => {
                    const v = row.values[i];
                    const isBest = best != null && v === best;
                    return (
                      <Text
                        key={i}
                        style={[styles.cell, styles.value, v != null && { color: scoreColor(v) }, isBest && styles.best]}>
                        {t}
                      </Text>
                    );
                  })}
                </View>
              </View>
            );
          })}
          <Text style={styles.muted}>Bold marks the higher score in each row. Tap a name to open its full rating.</Text>
        </View>
      )}
      {current && current.length < tickers.length && (
        <Text style={styles.muted}>
          No data for {tickers.filter((t) => !current.some((r) => r.ticker === t)).join(', ')}.
        </Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 12, gap: 10 },
  headerRow: { flexDirection: 'row', gap: 8, paddingLeft: 0 },
  cell: { flex: 1, minWidth: 0 },
  symbol: { fontSize: 16, fontWeight: '700', color: colors.text },
  name: { fontSize: 12, color: colors.muted },
  price: { fontSize: 13, color: colors.text, marginTop: 2, fontVariant: ['tabular-nums'] },
  remove: { fontSize: 12, color: colors.danger, marginTop: 4 },
  row: { gap: 2, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, paddingTop: 8 },
  rowLabel: { fontSize: 12, color: colors.muted, fontWeight: '600' },
  values: { flexDirection: 'row', gap: 8 },
  value: { fontSize: 14, color: colors.text, fontVariant: ['tabular-nums'] },
  best: { fontWeight: '800' },
  muted: { fontSize: 13, color: colors.muted, lineHeight: 18 },
  error: { color: colors.danger },
});

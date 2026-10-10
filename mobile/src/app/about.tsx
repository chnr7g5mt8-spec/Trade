import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { fetchMethodology, type Methodology, type MethodologyCategory, type TrackRecord } from '../lib/api';
import { colors, scoreColor } from '../lib/theme';

const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;

export default function About() {
  const [data, setData] = useState<Methodology | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchMethodology().then(
      (m) => {
        setData(m);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!data) {
    return (
      <View style={styles.center}>
        {error ? (
          <>
            <Text style={styles.error}>{error}</Text>
            <Pressable onPress={load} style={styles.retry} accessibilityRole="button">
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </>
        ) : (
          <ActivityIndicator size="large" />
        )}
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Section title="What the score means">
        <Text style={styles.body}>
          Every stock and coin gets a score from 0 to 100, built from the categories below. The label follows from the
          score:
        </Text>
        {data.labels.map((l, i) => {
          const upper = i === 0 ? 100 : data.labels[i - 1].min_score - 1;
          return (
            <View key={l.label} style={styles.row}>
              <View style={[styles.dot, { backgroundColor: scoreColor(l.min_score + 1) }]} />
              <Text style={styles.rowLabel}>{l.label}</Text>
              <Text style={styles.rowValue}>
                {l.min_score}–{upper}
              </Text>
            </View>
          );
        })}
        <Text style={styles.muted}>
          Funds, stablecoins and anything with less than {Math.round(data.min_coverage * 100)}% of the measures
          available are shown but not rated.
        </Text>
      </Section>

      <Section title="Stocks">
        <Text style={styles.body}>
          Measures marked “vs peers” are ranked against companies in the same industry (or the wider sector when the
          industry has fewer than {data.min_peers} companies with data): {Math.round(data.relative_weight * 100)}% of
          the points come from that ranking and {Math.round((1 - data.relative_weight) * 100)}% from a fixed scale, so a
          whole industry that is expensive doesn’t look cheap. Banks, insurers and lenders skip cash-flow, liquidity
          and debt measures, which don’t apply to them.
        </Text>
        <Text style={styles.muted}>
          {data.benchmarks.generated_at
            ? `Peer data: ${data.benchmarks.industries} industries and ${data.benchmarks.sectors} sectors, updated ${data.benchmarks.generated_at}.`
            : 'Peer data is being prepared; until then every measure uses its fixed scale.'}
        </Text>
        <Categories categories={data.stock_categories} />
      </Section>

      <Section title="Crypto">
        <Text style={styles.body}>
          Coins have no earnings, so they are rated on size and trading activity, price trend, risk and maturity. Scores
          compare coins with each other; even the best-rated coins are far more volatile than most stocks.
        </Text>
        <Categories categories={data.crypto_categories} />
      </Section>

      <Section title="Track record">
        {data.track_record?.summary ? (
          <Track record={data.track_record} />
        ) : (
          <Text style={styles.body}>
            The historical test hasn’t finished yet. It re-rates the largest US companies at past dates, using only
            information available then, and checks how the ratings did over the following year.
          </Text>
        )}
      </Section>

      <Text style={styles.footnote}>
        Data from Yahoo Finance. Educational use only, not investment advice.
      </Text>
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle} accessibilityRole="header">
        {title}
      </Text>
      {children}
    </View>
  );
}

function Categories({ categories }: { categories: MethodologyCategory[] }) {
  return (
    <View style={{ gap: 10, marginTop: 4 }}>
      {categories.map((c) => (
        <View key={c.key} style={{ gap: 2 }}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>{c.label}</Text>
            <Text style={styles.rowValue}>{c.optional ? 'dividend payers only' : `${Math.round(c.weight * 100)}%`}</Text>
          </View>
          <Text style={styles.muted}>
            {c.metrics.map((m) => (m.relative ? `${m.label} (vs peers)` : m.label)).join(' · ')}
          </Text>
        </View>
      ))}
    </View>
  );
}

function Track({ record }: { record: TrackRecord }) {
  const s = record.summary!;
  const quintiles = s.quintile_returns;
  const max = Math.max(0.01, ...quintiles.map((q) => Math.abs(q ?? 0)));
  const names = ['Lowest 20%', 'Next 20%', 'Middle 20%', 'Next 20%', 'Highest 20%'];
  const order = ['Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'];
  return (
    <View style={{ gap: 10 }}>
      <Text style={styles.body}>{record.method}</Text>
      <Text style={styles.muted}>
        {record.universe}. {s.test_dates} start dates, {s.observations.toLocaleString('en-US')} ratings in total.
      </Text>

      <Text style={styles.subTitle}>Average return over the next 12 months, by score</Text>
      {quintiles
        .map((q, i) => ({ q, name: names[i] }))
        .reverse()
        .map(({ q, name }, i) => (
          <View key={i} style={styles.barRow}>
            <Text style={styles.barLabel}>{name}</Text>
            <View style={styles.barTrack}>
              <View
                style={[
                  styles.barFill,
                  { width: `${(Math.abs(q ?? 0) / max) * 100}%`, backgroundColor: (q ?? 0) >= 0 ? '#16A34A' : colors.danger },
                ]}
              />
            </View>
            <Text style={styles.barValue}>{pct(q)}</Text>
          </View>
        ))}
      <Text style={styles.body}>
        Highest-scored fifth minus lowest-scored fifth: <Text style={styles.strong}>{pct(s.top_minus_bottom)}</Text> a
        year on average; the highest fifth did better at {Math.round(s.top_beat_bottom_share * 100)}% of start dates.
        Rank correlation between score and return: {s.rank_correlation == null ? '—' : s.rank_correlation.toFixed(2)}
        {s.rank_correlation_t != null ? ` (t = ${s.rank_correlation_t.toFixed(1)})` : ''}.
      </Text>

      <Text style={styles.subTitle}>By label</Text>
      {order
        .filter((l) => s.by_label[l])
        .map((l) => (
          <View key={l} style={styles.row}>
            <Text style={styles.rowLabel}>{l}</Text>
            <Text style={styles.rowValue}>
              {pct(s.by_label[l].average_return)} · {s.by_label[l].count} ratings
            </Text>
          </View>
        ))}

      <Text style={styles.subTitle}>Limits of this test</Text>
      {record.limitations.map((l) => (
        <Text key={l} style={styles.muted}>
          • {l}
        </Text>
      ))}
      <Text style={styles.muted}>Last run {record.generated_at}.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 16 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 16, gap: 10 },
  cardTitle: { fontSize: 18, fontWeight: '700', color: colors.text },
  subTitle: { fontSize: 14, fontWeight: '700', color: colors.text, marginTop: 6 },
  body: { color: colors.text, fontSize: 14, lineHeight: 20 },
  strong: { fontWeight: '700' },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowLabel: { flex: 1, color: colors.text, fontSize: 14, fontWeight: '600' },
  rowValue: { color: colors.muted, fontSize: 13, fontVariant: ['tabular-nums'] },
  dot: { width: 10, height: 10, borderRadius: 5 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: { width: 92, color: colors.text, fontSize: 13 },
  barTrack: { flex: 1, height: 10, borderRadius: 5, backgroundColor: colors.track, overflow: 'hidden' },
  barFill: { height: 10, borderRadius: 5 },
  barValue: { width: 64, textAlign: 'right', color: colors.text, fontSize: 13, fontVariant: ['tabular-nums'] },
  error: { color: colors.danger, textAlign: 'center' },
  retry: { backgroundColor: colors.accent, borderRadius: 10, paddingHorizontal: 18, paddingVertical: 10 },
  retryText: { color: '#fff', fontWeight: '600' },
  footnote: { fontSize: 12, color: colors.muted, textAlign: 'center', marginTop: 4 },
});

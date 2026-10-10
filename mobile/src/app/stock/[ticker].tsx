import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CategoryCard } from '../../components/CategoryCard';
import { ScoreRing } from '../../components/ScoreRing';
import { Sparkline } from '../../components/Sparkline';
import { fetchRating, type Rating } from '../../lib/api';
import { colors, formatMoney, scoreColor } from '../../lib/theme';
import { useWatchlist } from '../../lib/watchlist';

export default function StockDetail() {
  const { ticker: raw } = useLocalSearchParams<{ ticker: string }>();
  const ticker = String(raw ?? '').toUpperCase();
  const watchlist = useWatchlist();
  const [rating, setRating] = useState<Rating | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [chartWidth, setChartWidth] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRating(await fetchRating(ticker));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    load();
  }, [load]);

  const watching = watchlist.has(ticker);
  const header = (
    <Stack.Screen
      options={{
        title: ticker,
        // Only offer "Watch" once the ticker is known to resolve.
        headerRight: () =>
          rating && (
            <Pressable
              onPress={() => (watching ? watchlist.remove(ticker) : watchlist.add(ticker))}
              hitSlop={10}
              accessibilityRole="button"
              accessibilityLabel={watching ? 'Remove from watchlist' : 'Add to watchlist'}>
              <Text style={styles.watchButton}>{watching ? '★ Watching' : '☆ Watch'}</Text>
            </Pressable>
          ),
      }}
    />
  );

  if (loading && !rating) {
    return (
      <View style={styles.center}>
        {header}
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (error && !rating) {
    return (
      <View style={styles.center}>
        {header}
        <Text style={styles.error}>{error}</Text>
        <Pressable onPress={load} style={styles.retry} accessibilityRole="button">
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  if (!rating) return null;

  const history = rating.price_history;
  const up = history.length > 1 && history[history.length - 1] >= history[0];
  const upside =
    rating.analyst_target_price != null && rating.price ? rating.analyst_target_price / rating.price - 1 : null;

  return (
    <ScrollView
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
      {header}

      <View style={styles.hero}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.name}>{rating.name ?? rating.ticker}</Text>
          {rating.sector && <Text style={styles.muted}>{rating.sector}</Text>}
          <Text style={styles.price}>{formatMoney(rating.price, rating.currency)}</Text>
          <View style={[styles.pill, { backgroundColor: scoreColor(rating.score) }]}>
            <Text style={styles.pillText}>{rating.label}</Text>
          </View>
        </View>
        <ScoreRing score={rating.score} />
      </View>

      {history.length > 1 && (
        <View style={styles.card} onLayout={(e) => setChartWidth(e.nativeEvent.layout.width - 28)}>
          <Text style={styles.cardTitle}>Last 12 months</Text>
          <Sparkline data={history} width={chartWidth} height={90} color={up ? '#16A34A' : colors.danger} />
          <View style={styles.rangeRow}>
            <Text style={styles.muted}>52w low {formatMoney(rating.fifty_two_week_low, rating.currency)}</Text>
            <Text style={styles.muted}>52w high {formatMoney(rating.fifty_two_week_high, rating.currency)}</Text>
          </View>
        </View>
      )}

      <Text style={styles.sectionTitle}>Score breakdown</Text>
      {rating.categories.map((c) => (
        <CategoryCard key={c.key} category={c} />
      ))}

      {(rating.analyst_recommendation || rating.analyst_target_price != null) && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Wall Street analysts</Text>
          <Text style={styles.muted}>Shown for comparison; not part of the score.</Text>
          <View style={styles.rangeRow}>
            <Text style={styles.body}>Consensus: {rating.analyst_recommendation ?? '—'}</Text>
            <Text style={styles.body}>
              Target {formatMoney(rating.analyst_target_price, rating.currency)}
              {upside != null && ` (${upside >= 0 ? '+' : ''}${(upside * 100).toFixed(0)}%)`}
            </Text>
          </View>
        </View>
      )}

      <Text style={styles.footnote}>
        Based on {Math.round(rating.coverage * 100)}% of metrics · Source: {rating.source === 'sample' ? 'demo data' : 'Yahoo Finance'}
        {'\n'}Educational use only, not investment advice.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 16 },
  hero: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.card, borderRadius: 16, padding: 16, gap: 12 },
  name: { fontSize: 20, fontWeight: '700', color: colors.text },
  price: { fontSize: 26, fontWeight: '700', color: colors.text, marginTop: 4, fontVariant: ['tabular-nums'] },
  pill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 4, marginTop: 6 },
  pillText: { color: '#fff', fontWeight: '700' },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 8 },
  cardTitle: { fontSize: 16, fontWeight: '600', color: colors.text },
  rangeRow: { flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 8,
  },
  muted: { color: colors.muted, fontSize: 13 },
  body: { color: colors.text, fontSize: 14 },
  error: { color: colors.danger, textAlign: 'center' },
  retry: { backgroundColor: colors.accent, borderRadius: 10, paddingHorizontal: 18, paddingVertical: 10 },
  retryText: { color: '#fff', fontWeight: '600' },
  watchButton: { color: colors.accent, fontSize: 16, fontWeight: '600', paddingHorizontal: 8 },
  footnote: { fontSize: 12, color: colors.muted, textAlign: 'center', marginTop: 12, lineHeight: 18 },
});

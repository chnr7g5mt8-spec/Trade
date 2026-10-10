import { router, useFocusEffect } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, View } from 'react-native';

import { ScoreRing } from '../components/ScoreRing';
import { Sparkline } from '../components/Sparkline';
import { fetchRatings, type Rating } from '../lib/api';
import { colors, formatMoney, formatTime, marketLabel, scoreColor } from '../lib/theme';
import { useWatchlist } from '../lib/watchlist';

const REFRESH_MS = 60_000;

export default function Home() {
  const { list, ready } = useWatchlist();
  const [query, setQuery] = useState('');
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  // Tickers the last successful load asked for; those missing from the
  // response failed on the server and are shown as unavailable.
  const [requested, setRequested] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    if (!ready) return;
    const id = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const results = await fetchRatings(list);
      if (id !== latestRequest.current) return; // a newer load superseded this one
      setRatings(Object.fromEntries(results.map((r) => [r.ticker, r])));
      setRequested(new Set(list));
      setCheckedAt(Date.now() / 1000);
    } catch (e) {
      if (id === latestRequest.current) setError((e as Error).message);
    } finally {
      if (id === latestRequest.current) setLoading(false);
    }
  }, [list, ready]);

  const loaded = Object.values(ratings);
  const demo = loaded.some((r) => r.source === 'sample');
  const marketState = loaded.find((r) => r.market_state)?.market_state ?? null;
  const live = !demo && (marketState === 'open' || marketState === 'pre' || marketState === 'post');
  let marketStatus: string | null = null;
  if (demo) marketStatus = "Demo data · prices aren't live";
  else if (live) marketStatus = `${marketLabel(marketState)} · updates every minute · checked ${formatTime(checkedAt)}`;
  else if (marketState === 'closed') marketStatus = 'Market closed · showing the last closing prices';

  useFocusEffect(
    useCallback(() => {
      load();
      // Keep prices current while the market is trading and this screen is visible.
      if (!live) return;
      const timer = setInterval(load, REFRESH_MS);
      return () => clearInterval(timer);
    }, [load, live]),
  );

  const submit = () => {
    const ticker = query.trim().toUpperCase();
    if (!ticker) return;
    setQuery('');
    router.push({ pathname: '/stock/[ticker]', params: { ticker } });
  };

  return (
    <FlatList
      data={list}
      keyExtractor={(t) => t}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      ListHeaderComponent={
        <View style={styles.header}>
          <TextInput
            value={query}
            onChangeText={setQuery}
            onSubmitEditing={submit}
            placeholder="Rate a ticker, e.g. NVDA"
            placeholderTextColor={colors.muted}
            autoCapitalize="characters"
            autoCorrect={false}
            returnKeyType="search"
            style={styles.search}
            accessibilityLabel="Ticker symbol"
          />
          <View style={{ gap: 4 }}>
            <Text style={styles.sectionTitle}>Watchlist</Text>
            {marketStatus && <Text style={styles.marketStatus}>{marketStatus}</Text>}
          </View>
          {error && <Text style={styles.error}>{error}</Text>}
        </View>
      }
      ListEmptyComponent={
        ready ? <Text style={styles.empty}>Your watchlist is empty. Search a ticker to rate it.</Text> : null
      }
      ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
      renderItem={({ item }) => (
        <WatchRow ticker={item} rating={ratings[item]} unavailable={(requested.has(item) || error !== null) && !ratings[item]} />
      )}
      ListFooterComponent={
        <Text style={styles.disclaimer}>
          Scores are computed from public financial data for educational purposes only and are not investment advice.
        </Text>
      }
    />
  );
}

function WatchRow({ ticker, rating, unavailable }: { ticker: string; rating?: Rating; unavailable: boolean }) {
  const history = rating?.price_history ?? [];
  const up = history.length > 1 && history[history.length - 1] >= history[0];
  const status = rating ? rating.label : unavailable ? 'Unavailable' : '…';
  const a11y = [ticker, rating?.name, status !== '…' && status, rating?.score != null && `score ${rating.score}`]
    .filter(Boolean)
    .join(', ');

  return (
    <Pressable
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}
      onPress={() => router.push({ pathname: '/stock/[ticker]', params: { ticker } })}
      accessibilityRole="button"
      accessibilityLabel={a11y}>
      <ScoreRing score={rating?.score ?? null} size={52} stroke={5} showLabel={false} />
      <View style={styles.rowText}>
        <Text style={styles.ticker}>{ticker}</Text>
        <Text style={styles.name} numberOfLines={1}>
          {rating?.name ?? ' '}
        </Text>
      </View>
      <Sparkline data={history} width={60} height={28} color={up ? '#16A34A' : colors.danger} strokeWidth={1.5} />
      <View style={styles.rowRight}>
        <Text style={styles.price}>{formatMoney(rating?.price, rating?.currency)}</Text>
        <Text style={[styles.label, { color: scoreColor(rating?.score) }]}>{status}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 40 },
  header: { gap: 16, marginBottom: 12 },
  search: {
    backgroundColor: colors.card,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sectionTitle: { fontSize: 13, fontWeight: '600', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  marketStatus: { fontSize: 13, color: colors.muted },
  error: { color: colors.danger },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 24 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.card, borderRadius: 12, padding: 12 },
  rowText: { flex: 1, minWidth: 0 },
  ticker: { fontSize: 17, fontWeight: '700', color: colors.text },
  name: { fontSize: 13, color: colors.muted },
  rowRight: { alignItems: 'flex-end', minWidth: 84 },
  price: { fontSize: 15, fontWeight: '600', color: colors.text, fontVariant: ['tabular-nums'] },
  label: { fontSize: 13, fontWeight: '600' },
  disclaimer: { fontSize: 12, color: colors.muted, textAlign: 'center', marginTop: 24 },
});

import { router, useFocusEffect } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { ScoreRing } from '../components/ScoreRing';
import { SearchBox } from '../components/SearchBox';
import { Sparkline } from '../components/Sparkline';
import { fetchRatings, type Rating } from '../lib/api';
import { colors, formatMoney, formatTime, marketLabel, scoreColor } from '../lib/theme';
import { useWatchlist } from '../lib/watchlist';

const REFRESH_MS = 60_000;

export default function Home() {
  const { list, ready } = useWatchlist();
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
  const isLive = (s: string | null) => s === 'open' || s === 'pre' || s === 'post';
  // Crypto trades around the clock, so the market status line follows the stocks.
  const stockState = loaded.find((r) => r.asset_type !== 'crypto' && r.market_state)?.market_state ?? null;
  const hasCrypto = loaded.some((r) => r.asset_type === 'crypto');
  const live = !demo && (isLive(stockState) || hasCrypto);
  let marketStatus: string | null = null;
  if (demo) marketStatus = "Demo data · prices aren't live";
  else if (isLive(stockState)) marketStatus = `${marketLabel(stockState)} · updates every minute · checked ${formatTime(checkedAt)}`;
  else if (stockState === 'closed')
    marketStatus = hasCrypto
      ? 'Stock markets closed · crypto updates every minute'
      : 'Market closed · showing the last closing prices';
  else if (hasCrypto) marketStatus = `Crypto trades around the clock · updates every minute · checked ${formatTime(checkedAt)}`;

  useFocusEffect(
    useCallback(() => {
      load();
      // Keep prices current while the market is trading and this screen is visible.
      if (!live) return;
      const timer = setInterval(load, REFRESH_MS);
      return () => clearInterval(timer);
    }, [load, live]),
  );

  const open = (ticker: string) => router.push({ pathname: '/stock/[ticker]', params: { ticker } });

  return (
    <FlatList
      data={list}
      keyExtractor={(t) => t}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      ListHeaderComponent={
        <View style={styles.header}>
          <SearchBox onSelect={open} />
          <Pressable
            style={({ pressed }) => [styles.explore, pressed && { opacity: 0.7 }]}
            onPress={() => router.push('/explore')}
            accessibilityRole="link">
            <View style={{ flex: 1 }}>
              <Text style={styles.exploreTitle}>Explore top-rated stocks and crypto</Text>
              <Text style={styles.exploreText}>Top 20 by value, growth, dividends, low risk, momentum and sector</Text>
            </View>
            <Text style={styles.exploreArrow}>›</Text>
          </Pressable>
          <View style={{ gap: 4 }}>
            <Text style={styles.sectionTitle}>Watchlist</Text>
            {!!marketStatus && <Text style={styles.marketStatus}>{marketStatus}</Text>}
          </View>
          {!!error && <Text style={styles.error}>{error}</Text>}
        </View>
      }
      ListEmptyComponent={
        ready ? <Text style={styles.empty}>Your watchlist is empty. Search for a stock or coin to rate it.</Text> : null
      }
      ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
      renderItem={({ item }) => (
        <WatchRow ticker={item} rating={ratings[item]} unavailable={(requested.has(item) || error !== null) && !ratings[item]} />
      )}
      ListFooterComponent={
        <View style={styles.footer}>
          <Pressable onPress={() => router.push('/about')} accessibilityRole="link" hitSlop={8}>
            <Text style={styles.link}>How ratings work · track record</Text>
          </Pressable>
          <Text style={styles.disclaimer}>
            Scores are computed from public financial data for educational purposes only and are not investment advice.
          </Text>
        </View>
      }
    />
  );
}

function WatchRow({ ticker, rating, unavailable }: { ticker: string; rating?: Rating; unavailable: boolean }) {
  const history = rating?.price_history ?? [];
  const up = history.length > 1 && history[history.length - 1] >= history[0];
  const status = rating ? rating.label : unavailable ? 'Unavailable' : '…';
  const symbol = rating?.symbol ?? ticker.replace(/-USD$/, '');
  const a11y = [symbol, rating?.name, status !== '…' && status, rating?.score != null && `score ${rating.score}`]
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
        <Text style={styles.ticker}>{symbol}</Text>
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
  explore: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.accent, borderRadius: 12, padding: 14 },
  exploreTitle: { color: '#fff', fontSize: 16, fontWeight: '700' },
  exploreText: { color: '#DBEAFE', fontSize: 13, marginTop: 2 },
  exploreArrow: { color: '#fff', fontSize: 28, fontWeight: '300' },
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
  footer: { alignItems: 'center', gap: 12, marginTop: 24 },
  link: { color: colors.accent, fontSize: 14, fontWeight: '600' },
  disclaimer: { fontSize: 12, color: colors.muted, textAlign: 'center' },
});

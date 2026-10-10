import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ScoreRing } from '../components/ScoreRing';
import { fetchExplore, type Explore, type ExploreItem, type ExploreList } from '../lib/api';
import { colors, scoreColor } from '../lib/theme';

export default function ExploreScreen() {
  const { list: selectedKey } = useLocalSearchParams<{ list?: string }>();
  const [data, setData] = useState<Explore | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Only sets state once the request settles, so it is safe to call from an effect.
  const load = useCallback(() => {
    fetchExplore().then(
      (result) => {
        setData(result);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, []);

  const retry = () => {
    setError(null);
    load();
  };

  useEffect(() => {
    load();
  }, [load]);

  if (!data) {
    return (
      <View style={styles.center}>
        {error ? (
          <>
            <Text style={styles.error}>{error}</Text>
            <Pressable onPress={retry} style={styles.retry} accessibilityRole="button">
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </>
        ) : (
          <ActivityIndicator size="large" />
        )}
      </View>
    );
  }

  const current = data.lists.find((l) => l.key === selectedKey) ?? data.lists[0];
  const featured = data.lists.filter((l) => l.group === 'featured');
  const sectors = data.lists.filter((l) => l.group === 'sector');
  const etfs = data.lists.filter((l) => l.group === 'etf');
  const select = (key: string) => router.setParams({ list: key });

  return (
    <FlatList
      data={current?.items ?? []}
      keyExtractor={(item) => item.ticker}
      initialNumToRender={20}
      contentContainerStyle={styles.content}
      ListHeaderComponent={
        <View style={styles.header}>
          <Chips lists={featured} current={current?.key} onSelect={select} />
          {etfs.length > 0 && (
            <View style={{ gap: 6 }}>
              <Text style={styles.sectionTitle}>ETFs</Text>
              <Chips lists={etfs} current={current?.key} onSelect={select} />
            </View>
          )}
          {sectors.length > 0 && (
            <View style={{ gap: 6 }}>
              <Text style={styles.sectionTitle}>By sector</Text>
              <Chips lists={sectors} current={current?.key} onSelect={select} />
            </View>
          )}
          {!!current && (
            <View style={{ gap: 4 }}>
              <Text style={styles.title} accessibilityRole="header">
                {current.items.length === 20 ? `${current.title}: top 20` : current.title}
              </Text>
              <Text style={styles.muted}>{current.description}</Text>
            </View>
          )}
        </View>
      }
      ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
      renderItem={({ item, index }) => <Row item={item} rank={index + 1} list={current!} />}
      ListFooterComponent={
        <View style={styles.footer}>
          <Text style={styles.muted}>
            {data.generated_at
              ? `Ranked ${formatRankedAt(data.generated_at)} from ${counted(data)}: ${data.universe}. Tap one for its live rating.`
              : "Demo data: ranked from the recorded sample assets only, prices aren't live."}
          </Text>
          <Text style={styles.muted}>
            Ratings change as prices and results come in, and they haven’t been shown to predict returns (see the track
            record). Educational use only, not investment advice.
          </Text>
          <Pressable onPress={() => router.push('/about')} accessibilityRole="link" hitSlop={8}>
            <Text style={styles.link}>How ratings work · track record</Text>
          </Pressable>
        </View>
      }
    />
  );
}

function Chips({ lists, current, onSelect }: { lists: ExploreList[]; current?: string; onSelect: (key: string) => void }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
      {lists.map((l) => {
        const active = l.key === current;
        return (
          <Pressable
            key={l.key}
            onPress={() => onSelect(l.key)}
            style={[styles.chip, active && styles.chipActive]}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}>
            <Text style={[styles.chipText, active && styles.chipTextActive]}>{l.title}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function Row({ item, rank, list }: { item: ExploreItem; rank: number; list: ExploreList }) {
  const detail = list.asset_type === 'crypto' ? 'Crypto' : (item.industry ?? item.sector ?? '');
  const extra = list.category_label && item.category_score != null ? `${list.category_label} ${Math.round(item.category_score)}` : null;
  return (
    <Pressable
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}
      onPress={() => router.push({ pathname: '/stock/[ticker]', params: { ticker: item.ticker } })}
      accessibilityRole="button"
      accessibilityLabel={[`${rank}. ${item.symbol}`, item.name, item.label, `score ${item.score}`, extra]
        .filter(Boolean)
        .join(', ')}>
      <Text style={styles.rank}>{rank}</Text>
      <ScoreRing score={item.score} size={46} stroke={4} showLabel={false} />
      <View style={styles.rowText}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text style={styles.name} numberOfLines={1}>
          {item.name}
        </Text>
        {!!detail && (
          <Text style={styles.detail} numberOfLines={1}>
            {detail}
          </Text>
        )}
      </View>
      <View style={styles.rowRight}>
        <Text style={[styles.label, { color: scoreColor(item.score) }]}>{item.label}</Text>
        {!!extra && <Text style={styles.extra}>{extra}</Text>}
      </View>
    </Pressable>
  );
}

function counted(data: Explore): string {
  const parts = [`${data.stocks_rated.toLocaleString('en-US')} stocks`];
  if (data.etfs_rated) parts.push(`${data.etfs_rated.toLocaleString('en-US')} ETFs`);
  parts.push(`${data.coins_rated} coins`);
  return parts.length === 3 ? `${parts[0]}, ${parts[1]} and ${parts[2]}` : parts.join(' and ');
}

/** e.g. "Oct 9, 6:11 PM" in the viewer's own time zone. */
function formatRankedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 40 },
  header: { gap: 14, marginBottom: 12 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 16 },
  sectionTitle: { fontSize: 13, fontWeight: '600', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  chips: { gap: 8, paddingRight: 8 },
  chip: {
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { fontSize: 14, fontWeight: '600', color: colors.text },
  chipTextActive: { color: '#fff' },
  title: { fontSize: 20, fontWeight: '700', color: colors.text },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.card, borderRadius: 12, padding: 10 },
  rank: { width: 22, textAlign: 'center', color: colors.muted, fontSize: 14, fontWeight: '700', fontVariant: ['tabular-nums'] },
  rowText: { flex: 1, minWidth: 0 },
  symbol: { fontSize: 16, fontWeight: '700', color: colors.text },
  name: { fontSize: 13, color: colors.text },
  detail: { fontSize: 12, color: colors.muted },
  rowRight: { alignItems: 'flex-end', maxWidth: 130 },
  label: { fontSize: 13, fontWeight: '700' },
  extra: { fontSize: 12, color: colors.muted, fontVariant: ['tabular-nums'], textAlign: 'right' },
  footer: { gap: 10, marginTop: 20, alignItems: 'center' },
  link: { color: colors.accent, fontSize: 14, fontWeight: '600' },
  error: { color: colors.danger, textAlign: 'center' },
  retry: { backgroundColor: colors.accent, borderRadius: 10, paddingHorizontal: 18, paddingVertical: 10 },
  retryText: { color: '#fff', fontWeight: '600' },
});

import { useEffect, useState } from 'react';
import { Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { fetchNews, type NewsItem } from '../lib/api';
import { colors } from '../lib/theme';

function ago(unixSeconds: number | null): string {
  if (!unixSeconds) return '';
  const hours = Math.max(0, (Date.now() / 1000 - unixSeconds) / 3600);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

/** Recent headlines; tapping one opens the story in the browser. */
export function NewsCard({ ticker }: { ticker: string }) {
  const [items, setItems] = useState<{ ticker: string; news: NewsItem[] } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchNews(ticker).then(
      (news) => live && setItems({ ticker, news }),
      () => live && setFailed(ticker),
    );
    return () => {
      live = false;
    };
  }, [ticker]);

  const news = items?.ticker === ticker ? items.news : null;
  if (failed === ticker || (news && news.length === 0)) return null;

  return (
    <View style={styles.card}>
      <Text style={styles.title}>News</Text>
      {!news && <Text style={styles.muted}>Loading headlines…</Text>}
      {news?.map((n) => (
        <Pressable
          key={n.link}
          onPress={() => Linking.openURL(n.link)}
          style={({ pressed }) => [styles.row, pressed && { opacity: 0.6 }]}
          accessibilityRole="link"
          accessibilityLabel={`${n.title}. ${n.publisher ?? ''} ${ago(n.published)}`}>
          {n.thumbnail ? <Image source={{ uri: n.thumbnail }} style={styles.thumb} /> : <View style={styles.thumb} />}
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.headline} numberOfLines={3}>
              {n.title}
            </Text>
            <Text style={styles.muted}>{[n.publisher, ago(n.published)].filter(Boolean).join(' · ')}</Text>
          </View>
        </Pressable>
      ))}
      {!!news && <Text style={styles.muted}>Headlines from Yahoo Finance. Opens in your browser.</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 10 },
  title: { fontSize: 16, fontWeight: '600', color: colors.text },
  row: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  thumb: { width: 56, height: 56, borderRadius: 8, backgroundColor: colors.track },
  headline: { fontSize: 14, fontWeight: '600', color: colors.text, lineHeight: 19 },
  muted: { fontSize: 12, color: colors.muted },
});

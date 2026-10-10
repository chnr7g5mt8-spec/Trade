import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { CategoryScore } from '../lib/api';
import { colors, scoreColor } from '../lib/theme';

function Bar({ score }: { score: number | null }) {
  return (
    <View style={styles.track}>
      <View style={[styles.fill, { width: `${score ?? 0}%`, backgroundColor: scoreColor(score) }]} />
    </View>
  );
}

export function CategoryCard({ category }: { category: CategoryScore }) {
  const [open, setOpen] = useState(false);

  return (
    <Pressable
      onPress={() => setOpen((o) => !o)}
      style={styles.card}
      accessibilityRole="button"
      accessibilityLabel={`${category.label}, score ${category.score == null ? 'unavailable' : Math.round(category.score)}`}
      accessibilityHint={open ? 'Hide metric details' : 'Show metric details'}>
      <View style={styles.header}>
        <Text style={styles.title}>{category.label}</Text>
        <Text style={styles.weight}>{Math.round(category.weight * 100)}% weight</Text>
        <Text style={[styles.score, { color: scoreColor(category.score) }]}>
          {category.score == null ? '—' : Math.round(category.score)}
        </Text>
        <Text style={styles.chevron}>{open ? '▾' : '▸'}</Text>
      </View>
      <Bar score={category.score} />
      {open && (
        <View style={styles.metrics}>
          {category.metrics.map((m) => (
            <View key={m.key} style={styles.metricRow}>
              <Text style={styles.metricLabel}>{m.label}</Text>
              <Text style={styles.metricValue}>{m.display}</Text>
              <Text style={[styles.metricScore, { color: scoreColor(m.score) }]}>
                {m.score == null ? '—' : Math.round(m.score)}
              </Text>
            </View>
          ))}
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 10 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 16, fontWeight: '600', color: colors.text },
  weight: { flex: 1, fontSize: 12, color: colors.muted },
  score: { fontSize: 18, fontWeight: '700', minWidth: 32, textAlign: 'right' },
  chevron: { color: colors.muted, width: 12 },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.track, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4 },
  metrics: { gap: 8, paddingTop: 4, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  metricRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  metricLabel: { flex: 1, color: colors.text, fontSize: 14 },
  metricValue: { color: colors.muted, fontSize: 14, fontVariant: ['tabular-nums'] },
  metricScore: { width: 32, textAlign: 'right', fontWeight: '600', fontVariant: ['tabular-nums'] },
});

import { StyleSheet, Text, View } from 'react-native';

import type { FundProfile } from '../lib/api';
import { colors } from '../lib/theme';

const pct = (w: number) => `${(w * 100).toFixed(w >= 0.1 ? 0 : 1)}%`;

function Bars({ items }: { items: { name: string; weight: number }[] }) {
  const max = Math.max(...items.map((i) => i.weight));
  return (
    <View style={{ gap: 6 }}>
      {items.map((i) => (
        <View key={i.name} style={styles.barRow} accessibilityLabel={`${i.name} ${pct(i.weight)}`}>
          <Text style={styles.barLabel} numberOfLines={1}>
            {i.name}
          </Text>
          <View style={styles.track}>
            <View style={[styles.fill, { width: `${(i.weight / max) * 100}%` }]} />
          </View>
          <Text style={styles.barValue}>{pct(i.weight)}</Text>
        </View>
      ))}
    </View>
  );
}

/** What an ETF invests in: Yahoo's description, its mix, sectors and largest holdings. */
export function FundHoldings({ profile }: { profile: FundProfile }) {
  const top = profile.holdings.reduce((sum, h) => sum + h.weight, 0);
  return (
    <View style={styles.card}>
      <Text style={styles.title}>What it holds</Text>
      {!!profile.summary && <Text style={styles.body}>{profile.summary}</Text>}

      {profile.asset_mix.length > 0 && (
        <>
          <Text style={styles.subTitle}>Invests in</Text>
          <Bars items={profile.asset_mix} />
        </>
      )}

      {profile.sectors.length > 0 && (
        <>
          <Text style={styles.subTitle}>Sectors (of the stocks it holds)</Text>
          <Bars items={profile.sectors} />
        </>
      )}

      {profile.holdings.length > 0 && (
        <>
          <Text style={styles.subTitle}>
            Largest {profile.holdings.length} holdings · {pct(top)} of the fund
          </Text>
          {profile.holdings.map((h, i) => (
            <View key={`${h.symbol ?? h.name}-${i}`} style={styles.holding}>
              <Text style={styles.holdingName} numberOfLines={1}>
                {h.name}
                {h.symbol && h.symbol !== h.name ? <Text style={styles.muted}> · {h.symbol}</Text> : null}
              </Text>
              <Text style={styles.barValue}>{pct(h.weight)}</Text>
            </View>
          ))}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 8 },
  title: { fontSize: 16, fontWeight: '600', color: colors.text },
  subTitle: { fontSize: 13, fontWeight: '700', color: colors.text, marginTop: 6 },
  body: { fontSize: 14, color: colors.text, lineHeight: 20 },
  muted: { color: colors.muted },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: { width: 130, fontSize: 13, color: colors.text },
  track: { flex: 1, height: 8, borderRadius: 4, backgroundColor: colors.track, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.accent },
  barValue: { width: 48, textAlign: 'right', fontSize: 13, color: colors.text, fontVariant: ['tabular-nums'] },
  holding: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  holdingName: { flex: 1, fontSize: 14, color: colors.text },
});

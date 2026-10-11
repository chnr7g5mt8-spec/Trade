import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { fetchRating } from '../lib/api';
import { holdingsStore, removeHolding, upsertHolding } from '../lib/portfolio';
import { colors, formatMoney } from '../lib/theme';

function parseNumber(text: string): number | null {
  const v = Number(text.replace(/[,\s$]/g, ''));
  return text.trim() && Number.isFinite(v) ? v : null;
}

/** Add a holding (shares and price paid), or change or remove one. */
export function HoldingEditor({ ticker, onDone }: { ticker: string; onDone?: () => void }) {
  const holdings = holdingsStore.use();
  const existing = holdings.value.find((h) => h.ticker === ticker);
  const [shares, setShares] = useState(existing ? String(existing.shares) : '');
  const [cost, setCost] = useState(existing?.cost != null ? String(existing.cost) : '');
  const [info, setInfo] = useState<{ name: string; currency: string | null; price: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchRating(ticker).then(
      (r) => live && setInfo({ name: r.name ?? r.symbol, currency: r.currency, price: r.price }),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [ticker]);

  const save = () => {
    const n = parseNumber(shares);
    const c = parseNumber(cost);
    if (n == null || n <= 0) return setError('Enter how many shares (or units/coins) you own.');
    if (cost.trim() && (c == null || c < 0)) return setError('Enter the price you paid per share, or leave it empty.');
    upsertHolding({ ticker, shares: n, cost: c });
    setError(null);
    onDone?.();
  };

  const currency = info?.currency ?? '';
  return (
    <View style={styles.box}>
      <Text style={styles.title}>{existing ? `Edit ${ticker}` : `Add ${ticker} to your portfolio`}</Text>
      {!!info && (
        <Text style={styles.muted}>
          {info.name} · now {formatMoney(info.price, info.currency)}
        </Text>
      )}
      <View style={styles.row}>
        <View style={styles.field}>
          <Text style={styles.label}>Shares</Text>
          <TextInput
            value={shares}
            onChangeText={setShares}
            keyboardType="decimal-pad"
            placeholder="e.g. 100"
            placeholderTextColor={colors.muted}
            style={styles.input}
            accessibilityLabel="Number of shares"
          />
        </View>
        <View style={styles.field}>
          <Text style={styles.label}>Price paid per share{currency ? ` (${currency})` : ''}</Text>
          <TextInput
            value={cost}
            onChangeText={setCost}
            keyboardType="decimal-pad"
            placeholder={info?.price != null ? String(Number(info.price.toFixed(2))) : 'optional'}
            placeholderTextColor={colors.muted}
            style={styles.input}
            accessibilityLabel="Price paid per share"
          />
        </View>
      </View>
      {!!error && <Text style={styles.error}>{error}</Text>}
      <View style={styles.row}>
        <Pressable onPress={save} style={[styles.button, { flex: 1 }]} accessibilityRole="button">
          <Text style={styles.buttonText}>{existing ? 'Save' : 'Add to portfolio'}</Text>
        </Pressable>
        {existing ? (
          <Pressable
            onPress={() => {
              removeHolding(ticker);
              onDone?.();
            }}
            style={[styles.button, styles.remove]}
            accessibilityRole="button">
            <Text style={[styles.buttonText, { color: colors.danger }]}>Remove</Text>
          </Pressable>
        ) : (
          onDone && (
            <Pressable onPress={onDone} style={[styles.button, styles.remove]} accessibilityRole="button">
              <Text style={[styles.buttonText, { color: colors.text }]}>Cancel</Text>
            </Pressable>
          )
        )}
      </View>
      <Text style={styles.muted}>Leave the price empty to skip gain/loss for this holding.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 10, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 15, fontWeight: '700', color: colors.text },
  muted: { fontSize: 12, color: colors.muted },
  row: { flexDirection: 'row', gap: 10 },
  field: { flex: 1, gap: 4 },
  label: { fontSize: 12, color: colors.muted, fontWeight: '600' },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8, fontSize: 16, color: colors.text },
  error: { color: colors.danger, fontSize: 13 },
  button: { backgroundColor: colors.accent, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 14, alignItems: 'center' },
  remove: { backgroundColor: colors.bg },
  buttonText: { color: '#fff', fontWeight: '700' },
});

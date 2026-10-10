import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { searchAssets, type SearchResult } from '../lib/api';
import { colors } from '../lib/theme';

const DEBOUNCE_MS = 300;

type Props = { onSelect: (ticker: string) => void };

/** Search by company/coin name or symbol, with suggestions as you type. */
export function SearchBox({ onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ query: string; items: SearchResult[] } | null>(null);
  const [error, setError] = useState<{ query: string; message: string } | null>(null);
  const latest = useRef(0);
  const trimmed = query.trim();

  useEffect(() => {
    if (!trimmed) return;
    const id = ++latest.current;
    const timer = setTimeout(() => {
      searchAssets(trimmed).then(
        (items) => {
          if (id === latest.current) setResults({ query: trimmed, items });
        },
        (e: Error) => {
          if (id === latest.current) setError({ query: trimmed, message: e.message });
        },
      );
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [trimmed]);

  // Only show results that belong to what's typed now.
  const items = trimmed && results?.query === trimmed ? results.items : [];
  const searching = !!trimmed && results?.query !== trimmed && error?.query !== trimmed;
  const failed = trimmed && error?.query === trimmed && results?.query !== trimmed ? error.message : null;

  const choose = (ticker: string) => {
    setQuery('');
    setResults(null);
    onSelect(ticker);
  };

  const submit = () => {
    if (!trimmed) return;
    const upper = trimmed.toUpperCase();
    const exact = items.find((r) => r.ticker === upper || r.symbol === upper);
    choose(exact?.ticker ?? items[0]?.ticker ?? upper);
  };

  return (
    <View style={styles.wrapper}>
      <View style={styles.inputRow}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={submit}
          placeholder="Search any stock, fund or crypto"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="search"
          style={styles.input}
          accessibilityLabel="Search stocks, funds and crypto"
        />
        {searching && <ActivityIndicator style={styles.spinner} />}
      </View>
      {!!failed && <Text style={styles.error}>{failed}</Text>}
      {items.length > 0 && (
        <View style={styles.results} accessibilityRole="list">
          {items.map((r) => (
            <Pressable
              key={r.ticker}
              onPress={() => choose(r.ticker)}
              style={({ pressed }) => [styles.result, pressed && { backgroundColor: colors.bg }]}
              accessibilityRole="button"
              accessibilityLabel={`${r.name}, ${r.symbol}, ${badge(r)}`}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.symbol}>{r.symbol}</Text>
                <Text style={styles.name} numberOfLines={1}>
                  {r.name}
                </Text>
              </View>
              <Text style={styles.badge} numberOfLines={1}>
                {badge(r)}
              </Text>
            </Pressable>
          ))}
        </View>
      )}
      {!!trimmed && results?.query === trimmed && items.length === 0 && (
        <Text style={styles.empty}>No stocks, funds or coins match “{trimmed}”.</Text>
      )}
    </View>
  );
}

function badge(r: SearchResult): string {
  if (r.asset_type === 'crypto') return 'Crypto';
  if (r.asset_type === 'fund') return r.exchange ? `Fund · ${r.exchange}` : 'Fund';
  return r.exchange ?? 'Stock';
}

const styles = StyleSheet.create({
  wrapper: { gap: 6 },
  inputRow: { justifyContent: 'center' },
  input: {
    backgroundColor: colors.card,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    paddingRight: 40,
    fontSize: 16,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
  spinner: { position: 'absolute', right: 12 },
  results: { backgroundColor: colors.card, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  result: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  symbol: { fontSize: 15, fontWeight: '700', color: colors.text },
  name: { fontSize: 13, color: colors.muted },
  badge: { fontSize: 12, color: colors.muted, maxWidth: 140 },
  empty: { color: colors.muted, fontSize: 13, paddingHorizontal: 4 },
  error: { color: colors.danger, fontSize: 13, paddingHorizontal: 4 },
});

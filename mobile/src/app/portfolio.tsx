import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { HoldingEditor } from '../components/HoldingEditor';
import { ScoreRing } from '../components/ScoreRing';
import { SearchBox } from '../components/SearchBox';
import { alertsStore, checkAlerts } from '../lib/alerts';
import { fetchFx, fetchRatings, type Rating } from '../lib/api';
import { createBackup, restoreBackup } from '../lib/backup';
import {
  holdingsStore,
  neededPairs,
  project,
  settingsStore,
  summarize,
  type BaseCurrency,
  type Rates,
} from '../lib/portfolio';
import { useProfile } from '../lib/profile';
import { colors, scoreColor } from '../lib/theme';

function money(v: number | null | undefined, currency: string, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = v < 0 ? '−' : '';
  return `${sign}${currency === 'CAD' ? 'C$' : '$'}${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`);

function day(unix: number): string {
  return new Date(unix * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function Portfolio() {
  const holdings = holdingsStore.use();
  const settings = settingsStore.use();
  const alerts = alertsStore.use();
  const { profile, ready: profileReady } = useProfile();
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; ratings: Rating[]; rates: Rates } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const base: BaseCurrency = settings.value.currency;
  const tickers = holdings.value.map((h) => h.ticker).join(',');
  const ready = holdings.ready && settings.ready && profileReady;
  const key = `${tickers}|${base}|${profile}|${nonce}`;
  const dropAlert = settings.value.dropAlert;

  // Reload whenever the screen comes back into view (prices move).
  useFocusEffect(
    useCallback(() => {
      setNonce((n) => n + 1);
    }, [setNonce]),
  );

  useEffect(() => {
    if (!ready) return;
    let live = true;
    (async () => {
      const ratings = await fetchRatings(tickers ? tickers.split(',') : [], profile);
      const fx = await fetchFx(neededPairs(ratings, base));
      return { ratings, rates: fx.rates };
    })().then(
      (r) => {
        if (!live) return;
        setResult({ key, ...r });
        checkAlerts(r.ratings, dropAlert);
      },
      (e: Error) => live && setFailure({ key, message: e.message }),
    );
    return () => {
      live = false;
    };
  }, [key, ready, tickers, base, profile, dropAlert]);

  const ratings = result?.ratings ?? [];
  const rates = result?.rates ?? {};
  const loading = ready && result?.key !== key && failure?.key !== key;
  const error = failure?.key === key ? failure.message : null;
  const load = () => setNonce((n) => n + 1);

  const summary = summarize(holdings.value, ratings, base, rates);

  if (!holdings.ready) return <ActivityIndicator style={{ marginTop: 40 }} />;

  const empty = holdings.value.length === 0;
  return (
    <ScrollView contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
      <SearchBox onSelect={(t) => setEditing(t.toUpperCase())} />
      {!!editing && !holdings.value.some((h) => h.ticker === editing) && (
        <HoldingEditor ticker={editing} onDone={() => setEditing(null)} />
      )}
      {empty && !editing && (
        <View style={styles.card}>
          <Text style={styles.title}>Your portfolio</Text>
          <Text style={styles.body}>
            Search above to add what you own, with the number of shares and what you paid. You’ll see its value, gain
            or loss, your dividend income month by month, upcoming dividends, your sector mix and a portfolio score.
          </Text>
          <Text style={styles.muted}>Everything stays on this device. Use a backup code (below) to move it to another one.</Text>
        </View>
      )}
      {!!error && <Text style={styles.error}>{error}</Text>}

      {!empty && (
        <View style={styles.card}>
          <View style={styles.summaryRow}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.muted}>Total value</Text>
              <Text style={styles.big}>{money(summary.value, base)}</Text>
              {summary.gain != null && (
                <Text style={[styles.body, { color: summary.gain >= 0 ? '#15803D' : colors.danger }]}>
                  {summary.gain >= 0 ? '+' : ''}
                  {money(summary.gain, base)} ({summary.cost ? pct(summary.gain / summary.cost) : '—'})
                </Text>
              )}
            </View>
            <View style={{ alignItems: 'center' }}>
              <ScoreRing score={summary.score} size={72} stroke={7} showLabel={false} />
              <Text style={styles.muted}>Portfolio score</Text>
            </View>
          </View>
          <View style={styles.statRow}>
            <Stat label="Dividends a year" value={money(summary.income, base)} />
            <Stat label="A month (average)" value={money(summary.income / 12, base)} />
            <Stat label="Yield" value={pct(summary.yield)} />
            <Stat label="Yield on cost" value={pct(summary.yieldOnCost)} />
          </View>
          <CurrencyToggle value={base} onChange={(c) => settings.set((s) => ({ ...s, currency: c }))} />
          {summary.missing.length > 0 && (
            <Text style={styles.muted}>No price or exchange rate yet for {summary.missing.join(', ')}; not counted.</Text>
          )}
          <Text style={styles.muted}>
            Values in {base} at today’s exchange rates. The portfolio score is each holding’s score weighted by its value.
          </Text>
        </View>
      )}

      {alerts.value.length > 0 && (
        <View style={styles.card}>
          <View style={styles.headerRow}>
            <Text style={styles.title}>Alerts</Text>
            <Pressable onPress={() => alerts.set([])} accessibilityRole="button" hitSlop={8}>
              <Text style={styles.link}>Clear all</Text>
            </Pressable>
          </View>
          {alerts.value.map((a) => (
            <View key={a.id} style={styles.alertRow}>
              <Text style={styles.alertIcon}>{a.kind === 'drop' ? '↓' : a.kind === 'dividend' ? '$' : '★'}</Text>
              <Text style={[styles.body, { flex: 1 }]}>
                {a.message} <Text style={styles.muted}>{day(a.at)}</Text>
              </Text>
              <Pressable onPress={() => alerts.set((list) => list.filter((x) => x.id !== a.id))} accessibilityLabel="Dismiss alert" hitSlop={8}>
                <Text style={styles.muted}>✕</Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}

      {summary.positions.map((p) => {
        const r = p.rating;
        const isEditing = editing === p.holding.ticker;
        return (
          <View key={p.holding.ticker} style={styles.card}>
            <Pressable
              style={styles.holdingRow}
              onPress={() => router.push({ pathname: '/stock/[ticker]', params: { ticker: p.holding.ticker } })}
              accessibilityRole="button"
              accessibilityLabel={`${r?.symbol ?? p.holding.ticker}, ${p.holding.shares} shares, value ${money(p.value, base)}`}>
              <ScoreRing score={r?.score ?? null} size={44} stroke={4} showLabel={false} />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.symbol}>{r?.symbol ?? p.holding.ticker}</Text>
                <Text style={styles.muted} numberOfLines={1}>
                  {p.holding.shares.toLocaleString('en-US')} shares{r?.name ? ` · ${r.name}` : ''}
                </Text>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <Text style={styles.value}>{money(p.value, base)}</Text>
                {p.gain != null && p.cost ? (
                  <Text style={{ color: p.gain >= 0 ? '#15803D' : colors.danger, fontSize: 13 }}>
                    {p.gain >= 0 ? '+' : ''}
                    {pct(p.gain / p.cost)}
                  </Text>
                ) : (
                  <Text style={[styles.muted, { color: scoreColor(r?.score) }]}>{r?.label ?? ''}</Text>
                )}
              </View>
            </Pressable>
            <View style={styles.headerRow}>
              <Text style={styles.muted}>
                {pct(p.weight, 0)} of portfolio{p.income ? ` · ${money(p.income, base)} a year in dividends` : ''}
              </Text>
              <Pressable onPress={() => setEditing(isEditing ? null : p.holding.ticker)} accessibilityRole="button" hitSlop={8}>
                <Text style={styles.link}>{isEditing ? 'Close' : 'Edit'}</Text>
              </Pressable>
            </View>
            {isEditing && <HoldingEditor ticker={p.holding.ticker} onDone={() => setEditing(null)} />}
          </View>
        );
      })}

      {!empty && summary.sectors.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.title}>Mix</Text>
          {summary.sectors.map((s) => (
            <Bar key={s.name} label={s.name} fraction={s.weight} text={pct(s.weight, 0)} />
          ))}
          {summary.warnings.map((w) => (
            <Text key={w} style={styles.warning}>
              {w}
            </Text>
          ))}
          {summary.warnings.length === 0 && summary.positions.length > 1 && (
            <Text style={styles.muted}>No single holding or sector dominates.</Text>
          )}
        </View>
      )}

      {!empty && <DividendCalendar summary={summary} base={base} />}
      {!empty && summary.value > 0 && <Projection summary={summary} base={base} />}

      <AlertSettings value={settings.value.dropAlert} onChange={(v) => settings.set((s) => ({ ...s, dropAlert: v }))} />
      <Backup />
      <Text style={styles.footnote}>Educational use only, not investment advice. Dividends are expected from each company’s usual schedule and can change.</Text>
    </ScrollView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Bar({ label, fraction, text }: { label: string; fraction: number; text: string }) {
  return (
    <View style={styles.barRow} accessibilityLabel={`${label} ${text}`}>
      <Text style={styles.barLabel} numberOfLines={1}>
        {label}
      </Text>
      <View style={styles.track}>
        <View style={[styles.fill, { width: `${Math.max(0, Math.min(1, fraction)) * 100}%` }]} />
      </View>
      <Text style={styles.barValue}>{text}</Text>
    </View>
  );
}

function Chips<T extends string | number>({ options, value, onChange, label }: { options: { key: T; text: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <View style={styles.chips}>
      {options.map((o) => {
        const active = o.key === value;
        return (
          <Pressable
            key={String(o.key)}
            onPress={() => onChange(o.key)}
            style={[styles.chip, active && styles.chipActive]}
            accessibilityRole="radio"
            accessibilityState={{ checked: active }}
            aria-checked={active}
            accessibilityLabel={`${label} ${o.text}`}>
            <Text style={[styles.chipText, active && styles.chipTextActive]}>{o.text}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function CurrencyToggle({ value, onChange }: { value: BaseCurrency; onChange: (c: BaseCurrency) => void }) {
  return (
    <Chips
      label="Show in"
      value={value}
      onChange={onChange}
      options={[
        { key: 'USD', text: 'US dollars' },
        { key: 'CAD', text: 'Canadian dollars' },
      ]}
    />
  );
}

function DividendCalendar({ summary, base }: { summary: ReturnType<typeof summarize>; base: string }) {
  const max = Math.max(...summary.months.map((m) => m.amount), 0);
  const next = summary.payments.slice(0, 8);
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Dividend calendar</Text>
      {summary.payments.length === 0 ? (
        <Text style={styles.muted}>None of your holdings pays a regular dividend.</Text>
      ) : (
        <>
          <Text style={styles.subTitle}>Coming up (own before the ex-dividend date)</Text>
          {next.map((p) => (
            <View key={`${p.ticker}-${p.date}`} style={styles.headerRow} accessibilityLabel={`${p.symbol} about ${day(p.date)}, ${money(p.amount, base, 2)}`}>
              <Text style={styles.body}>
                {day(p.date)} · <Text style={styles.strong}>{p.symbol}</Text>
              </Text>
              <Text style={styles.value}>{money(p.amount, base, 2)}</Text>
            </View>
          ))}
          <Text style={styles.subTitle}>Next 12 months</Text>
          <View style={styles.monthRow}>
            {summary.months.map((m, i) => (
              <View key={`${m.label}-${i}`} style={styles.monthCol} accessibilityLabel={`${m.label} ${money(m.amount, base)}`}>
                <View style={styles.monthTrack}>
                  <View style={[styles.monthFill, { height: `${max ? (m.amount / max) * 100 : 0}%` }]} />
                </View>
                <Text style={styles.monthLabel}>{m.label[0]}</Text>
              </View>
            ))}
          </View>
          <Text style={styles.muted}>
            Expected ex-dividend dates from each company’s usual schedule; payment usually follows a few weeks later.
            Before any tax withheld.
          </Text>
        </>
      )}
    </View>
  );
}

function Projection({ summary, base }: { summary: ReturnType<typeof summarize>; base: string }) {
  const [years, setYears] = useState(10);
  const [priceGrowth, setPriceGrowth] = useState(0.04);
  const divGrowth = summary.dividendGrowth ?? 0.03;
  const reinvested = project(summary.value, summary.income, years, priceGrowth, divGrowth, true);
  const cash = project(summary.value, summary.income, years, priceGrowth, divGrowth, false);
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Reinvesting dividends</Text>
      <Chips label="Years" value={years} onChange={setYears} options={[5, 10, 20].map((y) => ({ key: y, text: `${y} years` }))} />
      <Chips
        label="Price growth"
        value={priceGrowth}
        onChange={setPriceGrowth}
        options={[0, 0.02, 0.04, 0.07].map((g) => ({ key: g, text: `${Math.round(g * 100)}% a year` }))}
      />
      <View style={styles.statRow}>
        <Stat label="Value, reinvesting" value={money(reinvested.value, base)} />
        <Stat label="Yearly income then" value={money(reinvested.income, base)} />
      </View>
      <Text style={styles.body}>
        Taking dividends as cash instead: {money(cash.value, base)} in holdings plus {money(cash.cash, base)} received,
        and {money(cash.income, base)} a year in income.
      </Text>
      <Text style={styles.muted}>
        Assumes prices grow {Math.round(priceGrowth * 100)}% a year and dividends {pct(divGrowth)} a year (your holdings’
        5-year dividend growth). An illustration, not a forecast; ignores taxes and fees.
      </Text>
    </View>
  );
}

function AlertSettings({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Alerts</Text>
      <Text style={styles.body}>
        When you open the app, it checks your portfolio and watchlist and alerts you when a rating label changes, a
        dividend is cut, or a price falls by:
      </Text>
      <Chips label="Alert on a drop of" value={value} onChange={onChange} options={[5, 10, 15, 20].map((v) => ({ key: v, text: `${v}%` }))} />
      <Text style={styles.muted}>Phone notifications will come with the App Store and Google Play versions.</Text>
    </View>
  );
}

function Backup() {
  const [code, setCode] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const make = async () => {
    const c = await createBackup();
    setCode(c);
    if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(c).then(
        () => setMessage({ ok: true, text: 'Backup code copied. Paste it into Restore on your other device.' }),
        () => setMessage({ ok: true, text: 'Select the code below and copy it.' }),
      );
    } else setMessage({ ok: true, text: 'Select the code below and copy it.' });
  };

  const restore = async () => {
    try {
      const summary = await restoreBackup(input);
      setMessage({ ok: true, text: summary });
      setInput('');
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Move to another device</Text>
      <Text style={styles.body}>
        Your portfolio, watchlist and settings are saved on this device only. A backup code carries them to another phone
        or computer; nothing is uploaded.
      </Text>
      <Pressable onPress={make} style={styles.button} accessibilityRole="button">
        <Text style={styles.buttonText}>Create backup code</Text>
      </Pressable>
      {!!code && (
        <TextInput value={code} editable={false} multiline selectTextOnFocus style={styles.code} accessibilityLabel="Backup code" />
      )}
      <TextInput
        value={input}
        onChangeText={setInput}
        placeholder="Paste a backup code to restore"
        placeholderTextColor={colors.muted}
        multiline
        style={styles.code}
        accessibilityLabel="Paste backup code"
        autoCapitalize="none"
        autoCorrect={false}
      />
      <Pressable onPress={restore} disabled={!input.trim()} style={[styles.button, !input.trim() && { opacity: 0.4 }]} accessibilityRole="button">
        <Text style={styles.buttonText}>Restore</Text>
      </Pressable>
      {!!message && <Text style={[styles.body, { color: message.ok ? '#15803D' : colors.danger }]}>{message.text}</Text>}
      <Text style={styles.muted}>Restoring replaces this device’s portfolio, watchlist and settings.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 10 },
  title: { fontSize: 16, fontWeight: '700', color: colors.text },
  subTitle: { fontSize: 13, fontWeight: '700', color: colors.text, marginTop: 4 },
  body: { fontSize: 14, color: colors.text, lineHeight: 20 },
  strong: { fontWeight: '700' },
  muted: { fontSize: 13, color: colors.muted, lineHeight: 18 },
  error: { color: colors.danger },
  warning: { fontSize: 13, color: '#92400E', backgroundColor: '#FEF3C7', borderRadius: 8, padding: 8, lineHeight: 18 },
  big: { fontSize: 28, fontWeight: '800', color: colors.text, fontVariant: ['tabular-nums'] },
  summaryRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  statRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  stat: { flexGrow: 1, flexBasis: '45%', backgroundColor: colors.bg, borderRadius: 10, padding: 10 },
  statValue: { fontSize: 16, fontWeight: '700', color: colors.text, fontVariant: ['tabular-nums'] },
  statLabel: { fontSize: 12, color: colors.muted },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  holdingRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  symbol: { fontSize: 16, fontWeight: '700', color: colors.text },
  value: { fontSize: 15, fontWeight: '600', color: colors.text, fontVariant: ['tabular-nums'] },
  link: { color: colors.accent, fontSize: 14, fontWeight: '600' },
  alertRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  alertIcon: { width: 18, textAlign: 'center', fontWeight: '800', color: colors.accent },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: { width: 130, fontSize: 13, color: colors.text },
  track: { flex: 1, height: 8, borderRadius: 4, backgroundColor: colors.track, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.accent },
  barValue: { width: 44, textAlign: 'right', fontSize: 13, color: colors.text, fontVariant: ['tabular-nums'] },
  monthRow: { flexDirection: 'row', gap: 4, height: 90, alignItems: 'flex-end' },
  monthCol: { flex: 1, alignItems: 'center', gap: 4, height: '100%' },
  monthTrack: { flex: 1, width: '70%', justifyContent: 'flex-end', backgroundColor: colors.bg, borderRadius: 4, overflow: 'hidden' },
  monthFill: { width: '100%', backgroundColor: '#16A34A', borderRadius: 4 },
  monthLabel: { fontSize: 11, color: colors.muted },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.text, borderColor: colors.text },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text },
  chipTextActive: { color: '#fff' },
  button: { backgroundColor: colors.accent, borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  buttonText: { color: '#fff', fontWeight: '700' },
  code: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 10, minHeight: 60, fontSize: 12, color: colors.text, fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }) },
  footnote: { fontSize: 12, color: colors.muted, textAlign: 'center' },
});

import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { fetchHistory, type ScoreHistory } from '../lib/api';
import { colors, scoreColor } from '../lib/theme';
import { Sparkline } from './Sparkline';

function day(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** How the overall score has moved, from the daily snapshots. */
export function ScoreHistoryCard({ ticker }: { ticker: string }) {
  const [history, setHistory] = useState<ScoreHistory | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let live = true;
    fetchHistory(ticker).then(
      (h) => live && setHistory(h),
      () => {},
    );
    return () => {
      live = false;
    };
  }, [ticker]);

  if (!history || history.ticker !== ticker) return null;
  const points = history.points;
  const first = points[0];
  const last = points[points.length - 1];

  return (
    <View style={styles.card} onLayout={(e) => setWidth(e.nativeEvent.layout.width - 28)}>
      <Text style={styles.title}>Score history</Text>
      {points.length < 2 ? (
        <Text style={styles.muted}>
          {points.length === 1
            ? `Recorded once so far (${last.score} on ${day(last.date)}). The score is saved every weekday, so the history builds up from here.`
            : 'Scores are saved every weekday for the stocks, ETFs and coins in the daily rankings; none is saved for this one yet.'}
        </Text>
      ) : (
        <>
          <Sparkline data={points.map((p) => p.score)} width={width} height={70} color={scoreColor(last.score)} />
          <Text style={styles.body}>
            {last.score === first.score
              ? `Steady at ${last.score} since ${day(first.date)}.`
              : `${last.score > first.score ? 'Up' : 'Down'} from ${first.score} on ${day(first.date)} to ${last.score} on ${day(last.date)}.`}
            {` Low ${Math.min(...points.map((p) => p.score))}, high ${Math.max(...points.map((p) => p.score))}.`}
          </Text>
          <Text style={styles.muted}>Balanced style, saved each weekday after the close.</Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 14, gap: 8 },
  title: { fontSize: 16, fontWeight: '600', color: colors.text },
  body: { fontSize: 14, color: colors.text },
  muted: { fontSize: 12, color: colors.muted, lineHeight: 17 },
});

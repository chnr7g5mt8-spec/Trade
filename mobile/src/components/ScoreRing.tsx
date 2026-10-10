import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { colors, scoreColor } from '../lib/theme';

type Props = { score: number | null; size?: number; stroke?: number; showLabel?: boolean };

export function ScoreRing({ score, size = 120, stroke = 10, showLabel = true }: Props) {
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const progress = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const color = scoreColor(score);

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.track} strokeWidth={stroke} fill="none" />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${circumference} ${circumference}`}
          strokeDashoffset={circumference * (1 - progress)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      <View style={[StyleSheet.absoluteFill, styles.center]}>
        <Text style={[styles.value, { fontSize: size * 0.3, color }]}>{score == null ? '—' : Math.round(score)}</Text>
        {showLabel && <Text style={[styles.outOf, { fontSize: size * 0.11 }]}>/ 100</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', justifyContent: 'center' },
  value: { fontWeight: '800' },
  outOf: { color: colors.muted, marginTop: -2 },
});

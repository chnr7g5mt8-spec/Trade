import Svg, { Polyline } from 'react-native-svg';

type Props = { data: number[]; width: number; height: number; color: string; strokeWidth?: number };

export function Sparkline({ data, width, height, color, strokeWidth = 2 }: Props) {
  if (data.length < 2 || width <= 0) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = strokeWidth;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = pad + (1 - (v - min) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <Svg width={width} height={height}>
      <Polyline points={points} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" />
    </Svg>
  );
}

import { StyleSheet, Text, View } from 'react-native';

import type { Rating } from '../lib/api';
import { colors, formatChange, formatMoney, formatTime, marketLabel } from '../lib/theme';

/** When the price is from, whether the market is open, and any pre/after-hours price. */
export function PriceStatus({ rating }: { rating: Rating }) {
  if (rating.source === 'sample') {
    return <Text style={styles.status}>Demo data, not a live price</Text>;
  }

  const time = formatTime(rating.price_time);
  const status = [marketLabel(rating.market_state), time && `price as of ${time}`].filter(Boolean).join(' · ');
  const extended =
    rating.extended_price != null && rating.price ? (
      <Text style={styles.extended}>
        {rating.extended_session === 'pre' ? 'Pre-market' : 'After hours'}:{' '}
        {formatMoney(rating.extended_price, rating.currency)} ({formatChange(rating.price, rating.extended_price)})
      </Text>
    ) : null;

  return (
    <View style={styles.container}>
      {status !== '' && <Text style={styles.status}>{status}</Text>}
      {extended}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 2 },
  status: { color: colors.muted, fontSize: 13 },
  extended: { color: colors.text, fontSize: 14, fontWeight: '600' },
});

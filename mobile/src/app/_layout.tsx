import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { colors } from '../lib/theme';

export default function RootLayout() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.bg },
        }}>
        <Stack.Screen name="index" options={{ title: 'Stock Rater' }} />
        <Stack.Screen name="stock/[ticker]" options={{ title: '' }} />
        <Stack.Screen name="explore" options={{ title: 'Explore' }} />
        <Stack.Screen name="compare" options={{ title: 'Compare' }} />
        <Stack.Screen name="portfolio" options={{ title: 'My portfolio' }} />
        <Stack.Screen name="privacy" options={{ title: 'Privacy' }} />
        <Stack.Screen name="about" options={{ title: 'How ratings work' }} />
      </Stack>
    </>
  );
}

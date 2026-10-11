import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { PROFILES, useProfile } from '../lib/profile';
import { colors } from '../lib/theme';

/** Choose the investing style that weights stocks' overall scores. */
export function ProfilePicker() {
  const { profile, setProfile } = useProfile();
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.title}>Investing style</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {PROFILES.map((p) => {
          const active = p.key === profile;
          return (
            <Pressable
              key={p.key}
              onPress={() => setProfile(p.key)}
              style={[styles.chip, active && styles.chipActive]}
              accessibilityRole="radio"
              accessibilityState={{ checked: active }}
              aria-checked={active}
              accessibilityLabel={`Investing style ${p.label}`}>
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{p.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 13, fontWeight: '600', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  row: { gap: 6, paddingRight: 8 },
  chip: {
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.text, borderColor: colors.text },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text },
  chipTextActive: { color: '#fff' },
});

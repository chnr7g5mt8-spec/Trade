import { ScrollView, StyleSheet, Text } from 'react-native';

import { colors } from '../lib/theme';

/** Privacy policy (the app stores require one, linked from the store listings). */
export default function Privacy() {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.title}>Privacy policy</Text>
      <Text style={styles.muted}>Last updated October 11, 2026</Text>
      <Section title="No account, no tracking">
        Stock Rater has no sign-in and no accounts. It has no advertising, no analytics and no tracking, and it doesn’t
        collect your name, email, contacts or location.
      </Section>
      <Section title="What stays on your device">
        Your watchlist, portfolio (holdings, share counts and prices paid), alert settings, investing style and alerts
        are saved only on your device. They are never uploaded. A backup code you create contains this information as
        text; it goes only where you paste or send it.
      </Section>
      <Section title="What the app sends">
        To show ratings, prices and news, the app asks the Stock Rater server for the symbols you look at (for example
        “AAPL”) and, for the portfolio, exchange rates. It never sends how many shares you own or what you paid. Like
        any web server, ours sees your device’s IP address with each request; its hosting provider may keep short-lived
        logs of requests to run and protect the service.
      </Section>
      <Section title="Data sources and links">
        Market data and news headlines come from Yahoo Finance through the Stock Rater server, so Yahoo doesn’t receive
        requests from your device. Tapping a news headline opens the story on the publisher’s or Yahoo’s website, whose
        own privacy policy then applies.
      </Section>
      <Section title="Children">The app isn’t directed at children under 13.</Section>
      <Section title="Changes">
        If this policy changes, the new version will be posted on this page with a new date.
      </Section>
      <Text style={styles.muted}>Educational use only, not investment advice.</Text>
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <Text style={styles.heading}>{title}</Text>
      <Text style={styles.body}>{children}</Text>
    </>
  );
}

const styles = StyleSheet.create({
  content: { padding: 20, gap: 8, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '800', color: colors.text },
  heading: { fontSize: 16, fontWeight: '700', color: colors.text, marginTop: 10 },
  body: { fontSize: 15, color: colors.text, lineHeight: 22 },
  muted: { fontSize: 13, color: colors.muted },
});

# Publishing Stock Rater to the App Store and Google Play

The app is ready to build. These steps need **your** accounts, so they can't be done for you.

| | Apple App Store | Google Play |
| --- | --- | --- |
| Developer account | [Apple Developer Program](https://developer.apple.com/programs/), US$99/year | [Google Play Console](https://play.google.com/console/signup), US$25 once |
| Approval time for the account | 1–2 days | 1–2 days (identity check) |
| Review of each release | about 1–3 days | a few hours to a few days |

You also need a free [Expo account](https://expo.dev/signup); Expo's EAS service builds the apps in the cloud,
so you don't need a Mac or Android Studio.

## What's already set up

- `mobile/app.json`: name, icon, Android adaptive icon, bundle ID / package `com.stockrater.app`
  (change it before the first upload if you'd like your own, e.g. `com.yourname.stockrater`; it can't be
  changed after), version 1.0.0, and "no non-exempt encryption" for Apple's export question.
- `mobile/eas.json`: `development`, `preview` and `production` builds, each pointing the app at the live
  server `https://stock-rater-n7st.onrender.com`; build numbers go up automatically.
- Privacy policy for the store listings: <https://stock-rater-n7st.onrender.com/privacy>
- The app collects no personal data and has no accounts or tracking (see the privacy page), which keeps the
  stores' privacy questionnaires short: answer **"No data collected"**.

## Steps

From the `mobile` folder on any computer with Node.js 20+:

```bash
npx eas-cli@latest login                 # your Expo account
npx eas-cli@latest build:configure       # links the project to your account; keep the existing eas.json
```

### Try it on your own phone first (no store needed)

```bash
npx eas-cli@latest build --profile preview --platform android   # installable .apk link
npx eas-cli@latest build --profile preview --platform ios        # needs the Apple account; registers your iPhone
```

### Release

```bash
npx eas-cli@latest build --profile production --platform all
npx eas-cli@latest submit --platform ios       # uploads to App Store Connect (asks for your Apple ID)
npx eas-cli@latest submit --platform android   # uploads to Play Console (needs a Google service-account key;
                                               # EAS prints a link explaining how to create it)
```

Then finish each store listing and send it for review.

## Store listing text (ready to paste)

**Name:** Stock Rater
**Subtitle (Apple, 30 characters):** Ratings for stocks, ETFs, crypto
**Category:** Finance
**Age rating:** 4+ / Everyone (no objectionable content)

**Short description (Google, 80 characters):**
Scores stocks, ETFs and crypto 0–100 and tracks your portfolio's dividends.

**Description:**

> Stock Rater scores stocks, ETFs and cryptocurrencies from 0 to 100 and explains every score.
>
> • Ratings for stocks worldwide, about 1,400 US ETFs and thousands of coins, from valuation, profitability,
>   growth, financial health, momentum, risk and dividends, compared with similar companies
> • Investing styles: weight scores for dividends, growth, value or safety
> • Explore: the top 20 in each category, by sector, Canadian (TSX) lists and ETF lists, updated every weekday
> • Analyst outlook: what Wall Street expects next year
> • My portfolio: value, gains, dividend income by month, a dividend calendar, a reinvestment projection,
>   sector mix and alerts when a rating changes, a dividend is cut or a price drops
> • Score history, news and side-by-side comparisons
> • No account and no tracking: your portfolio stays on your phone
>
> Stock Rater is for education and research. It isn't investment advice, and its ratings haven't been shown to
> predict returns; the app shows its own track record.

**Keywords (Apple, 100 characters):** stocks,dividends,ETF,crypto,portfolio,rating,TSX,investing,screener,watchlist

**Screenshots:** take them from the preview build (6.7" iPhone and a phone for Google), e.g. the watchlist,
a stock's score breakdown, Explore, and My portfolio.

## Things reviewers look for in finance apps

- Apple: finance apps from individuals are accepted when they don't trade, hold money or give personalised
  advice; Stock Rater does none of these, and every screen says it's educational. If asked, explain that
  ratings are computed from public data by published rules (the "How ratings work" page).
- Google Play: complete the "Financial features" declaration as **"My app doesn't provide any financial
  features"** (it has no trading, banking, loans or crypto exchange).

## Phone notifications (after the store release)

Alerts currently appear inside the app. Push notifications to the lock screen need the store version plus a
small addition (expo-notifications and a server job that knows which tickers each device follows). Ask for it
once the app is in the stores.

## Accounts and syncing across devices

The app works without accounts; a backup code (My portfolio → Move to another device) copies everything to
another device. Real sign-in and automatic sync need a database, for example a free
[Supabase](https://supabase.com) project. Create one and share its project URL and "anon" key to add it.

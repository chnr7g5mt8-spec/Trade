import { alertsStore, seenStore } from './alerts';
import { holdingsStore, settingsStore, type Holding, type Settings } from './portfolio';
import { profileStore, type ProfileKey } from './profile';
import { replaceWatchlist, watchlistSnapshot } from './watchlist';

/**
 * A backup code: everything kept on this device (watchlist, portfolio,
 * settings, investing style) as text, to move to another device without an
 * account. The code itself is the data; nothing is uploaded.
 */
const PREFIX = 'SR1:';

type Backup = { w: string[]; h: Holding[]; s: Settings; p: ProfileKey };

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** UTF-8 bytes of a string, without TextEncoder (not on every phone's JavaScript engine). */
function utf8(text: string): number[] {
  const bytes: number[] = [];
  const escaped = encodeURIComponent(text);
  for (let i = 0; i < escaped.length; i++) {
    if (escaped[i] === '%') {
      bytes.push(parseInt(escaped.slice(i + 1, i + 3), 16));
      i += 2;
    } else bytes.push(escaped.charCodeAt(i));
  }
  return bytes;
}

function fromUtf8(bytes: number[]): string {
  return decodeURIComponent(bytes.map((b) => `%${b.toString(16).padStart(2, '0')}`).join(''));
}

/** URL-safe base64 without padding. */
function encode(text: string): string {
  const b = utf8(text);
  let out = '';
  for (let i = 0; i < b.length; i += 3) {
    const n = (b[i] << 16) | ((b[i + 1] ?? 0) << 8) | (b[i + 2] ?? 0);
    const chars = [18, 12, 6, 0].map((s) => ALPHABET[(n >> s) & 63]);
    out += chars.slice(0, i + 2 > b.length ? 2 : i + 3 > b.length ? 3 : 4).join('');
  }
  return out;
}

function decode(code: string): string {
  const bytes: number[] = [];
  for (let i = 0; i < code.length; i += 4) {
    const chunk = code.slice(i, i + 4);
    const vals = [...chunk].map((c) => {
      const v = ALPHABET.indexOf(c);
      if (v < 0) throw new Error('bad character');
      return v;
    });
    if (vals.length < 2) throw new Error('truncated');
    const n = vals.reduce((acc, v, k) => acc | (v << (18 - 6 * k)), 0);
    bytes.push((n >> 16) & 255);
    if (vals.length > 2) bytes.push((n >> 8) & 255);
    if (vals.length > 3) bytes.push(n & 255);
  }
  return fromUtf8(bytes);
}

export async function createBackup(): Promise<string> {
  const data: Backup = {
    w: await watchlistSnapshot(),
    h: await holdingsStore.load(),
    s: await settingsStore.load(),
    p: await profileStore.load(),
  };
  return PREFIX + encode(JSON.stringify(data));
}

/** Restores a backup code; returns a short summary, or throws with a readable message. */
export async function restoreBackup(code: string): Promise<string> {
  const text = code.replace(/\s+/g, '');
  if (!text.startsWith(PREFIX)) throw new Error('That isn’t a Stock Rater backup code (it should start with SR1:).');
  let data: Backup;
  try {
    data = JSON.parse(decode(text.slice(PREFIX.length)));
  } catch {
    throw new Error('The backup code is incomplete or damaged. Copy the whole code and try again.');
  }
  const okList = Array.isArray(data.w) && data.w.every((t) => typeof t === 'string');
  const okHoldings = Array.isArray(data.h) && data.h.every((h) => typeof h?.ticker === 'string' && h.shares > 0);
  if (!okList || !okHoldings) throw new Error('The backup code is incomplete or damaged. Copy the whole code and try again.');
  await replaceWatchlist(data.w);
  await holdingsStore.update(() => data.h.map((h) => ({ ticker: h.ticker, shares: h.shares, cost: h.cost ?? null })));
  if (data.s?.currency === 'USD' || data.s?.currency === 'CAD') await settingsStore.update(() => data.s);
  if (typeof data.p === 'string') await profileStore.update(() => data.p);
  // Start alert tracking afresh for the restored holdings.
  await seenStore.update(() => ({}));
  await alertsStore.update(() => []);
  return `Restored ${data.h.length} holding${data.h.length === 1 ? '' : 's'} and ${data.w.length} watchlist item${data.w.length === 1 ? '' : 's'}.`;
}

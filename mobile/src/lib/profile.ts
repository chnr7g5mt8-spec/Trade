import { createStore } from './store';

export const PROFILES = [
  { key: 'balanced', label: 'Balanced' },
  { key: 'dividend', label: 'Dividend' },
  { key: 'growth', label: 'Growth' },
  { key: 'value', label: 'Value' },
  { key: 'safety', label: 'Safety first' },
] as const;

export type ProfileKey = (typeof PROFILES)[number]['key'];

const KEYS = PROFILES.map((p) => p.key) as string[];

/** The investing style the user picked; it weights stocks' overall scores. */
export const profileStore = createStore<ProfileKey>('profile:v1', 'balanced', (v) =>
  typeof v === 'string' && KEYS.includes(v) ? (v as ProfileKey) : null,
);

export function useProfile() {
  const { value, ready, set } = profileStore.use();
  return { profile: value, ready, setProfile: set };
}

export function profileLabel(key: string | null | undefined): string {
  return PROFILES.find((p) => p.key === key)?.label ?? 'Balanced';
}

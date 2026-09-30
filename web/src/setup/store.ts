/** Setup (C0) results carried from the setup screen into the sitting. Survives a reload. */
import type { HeadphoneResult } from '../audio/headphones';
import type { QualityReport } from '../audio/quality';

export interface SetupData {
  deviceId: string;
  deviceLabel: string;
  sampleRate: number;
  noise_floor: QualityReport | null;
  headphones: HeadphoneResult | null;
  sleep_h: number;
  stress: number;
  mood: number;
}

const KEY = 'ehnglish.setup';

export const defaultSetup: SetupData = {
  deviceId: '',
  deviceLabel: '',
  sampleRate: 0,
  noise_floor: null,
  headphones: null,
  sleep_h: 7,
  stress: 3,
  mood: 6,
};

export function loadSetup(): SetupData {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return { ...defaultSetup, ...(JSON.parse(raw) as Partial<SetupData>) };
  } catch {
    /* ignore */
  }
  return { ...defaultSetup };
}

export function saveSetup(s: SetupData): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

export function setupComplete(s: SetupData): boolean {
  return !!s.deviceId && !!s.noise_floor && !!s.headphones?.ok;
}

export function clientInfo(): Record<string, unknown> {
  return {
    ua: navigator.userAgent,
    lang: navigator.language,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: `${window.screen.width}x${window.screen.height}`,
    app_version: __APP_VERSION__,
  };
}

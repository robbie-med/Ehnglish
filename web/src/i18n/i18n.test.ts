import { describe, expect, it } from 'vitest';
import en from './en.json';
import ko from './ko.json';

function flatten(o: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(o).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null ? flatten(v as Record<string, unknown>, prefix + k + '.') : [prefix + k],
  );
}

describe('i18n', () => {
  it('has the same keys in English and Korean', () => {
    expect(flatten(ko).sort()).toEqual(flatten(en).sort());
  });
  it('has no empty strings', () => {
    for (const dict of [en, ko]) {
      const leaves = flatten(dict).map((k) => k.split('.').reduce((o: unknown, p) => (o as Record<string, unknown>)[p], dict));
      expect(leaves.every((s) => typeof s === 'string' && s.trim().length > 0)).toBe(true);
    }
  });
});

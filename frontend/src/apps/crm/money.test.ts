import { describe, expect, it } from 'vitest';
import { centsToInput, formatCents, inputToCents } from './money';

describe('money', () => {
  it('reads typed amounts as exact cents (no float drift)', () => {
    expect(inputToCents('1.15')).toBe(115);
    expect(inputToCents('$4,800')).toBe(480_000);
    expect(inputToCents('6750.5')).toBe(675_050);
    expect(inputToCents('.99')).toBe(99);
    expect(inputToCents('-20')).toBe(-2_000);
    expect(inputToCents('')).toBe(0);
  });

  it('refuses what is not an amount rather than guessing', () => {
    for (const bad of ['abc', '1.234', '1.2.3', '.', '-', '12e3']) expect(inputToCents(bad), bad).toBeNull();
  });

  it('round-trips the edit text and formats whole amounts without cents', () => {
    expect(centsToInput(675_050)).toBe('6750.50');
    expect(inputToCents(centsToInput(675_050))).toBe(675_050);
    expect(centsToInput(0)).toBe('');
    expect(formatCents(480_000)).toBe('$4,800');
    expect(formatCents(675_050)).toBe('$6,750.50');
  });
});

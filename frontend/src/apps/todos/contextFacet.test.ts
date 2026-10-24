import { describe, expect, it } from 'vitest';
import { contextOptions, matchesContexts, matchesPeople, peopleGroup } from './contextFacet';

describe('contextOptions', () => {
  it('offers ONE option per context regardless of case — two would share a React key', () => {
    // Contexts are free text, so the server can list `@home` and `@Home` side by side.
    expect(contextOptions(['@home', '@Home', '@Calls'])).toEqual([
      { value: '@home', label: '@home' },
      { value: '@calls', label: '@Calls' },
    ]);
    // …and the one chip still matches todos filed under either spelling.
    expect(matchesContexts('@Home', ['@home'])).toBe(true);
    expect(matchesContexts('@home', ['@home'])).toBe(true);
  });
});

describe('matchesPeople', () => {
  it('an empty selection matches everyone, even a todo with no people', () => {
    expect(matchesPeople(['Ana'], [])).toBe(true);
    expect(matchesPeople([], [])).toBe(true);
    expect(matchesPeople(undefined, [])).toBe(true);
  });
  it('a selection does not match a todo with no people', () => {
    expect(matchesPeople(undefined, ['Ana'])).toBe(false);
    expect(matchesPeople([], ['Ana'])).toBe(false);
  });
  it('matches when any selected person is involved, exactly', () => {
    expect(matchesPeople(['Ana', 'Bo'], ['Bo'])).toBe(true);
    expect(matchesPeople(['Anabel'], ['Ana'])).toBe(false);
  });
});

describe('peopleGroup', () => {
  it('maps each person to an option', () => {
    const onToggle = () => {};
    expect(peopleGroup(['Ana', 'Bo'], ['Bo'], onToggle)).toEqual({
      key: 'people', label: 'People',
      options: [{ value: 'Ana', label: 'Ana' }, { value: 'Bo', label: 'Bo' }],
      selected: ['Bo'], onToggle,
    });
  });
});

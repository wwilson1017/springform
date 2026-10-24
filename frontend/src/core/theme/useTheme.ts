import { useCallback, useEffect, useSyncExternalStore } from 'react';

type Theme = 'light' | 'dark';

/** Must match the anti-flash script in index.html, which applies `.dark` before React loads. */
const THEME_KEY = 'springform_theme';

// Survives across hook instances so an explicit toggle still wins over OS changes for the rest
// of the session even when localStorage is blocked.
let explicitPreferenceThisSession = false;

// Every mounted hook re-reads the DOM class on notify, so simultaneous consumers never drift.
const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void) {
  listeners.add(onStoreChange);
  return () => { listeners.delete(onStoreChange); };
}

/** The DOM class is the source of truth: index.html seeds it, applyTheme keeps it current. */
function currentDomTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

function hasExplicitPreference(): boolean {
  if (explicitPreferenceThisSession) return true;
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === 'dark' || stored === 'light';
  } catch {
    return false;
  }
}

// Page-background hexes mirrored from --color-sf-bg in index.css, for the mobile browser chrome.
const THEME_COLOR: Record<Theme, string> = { light: '#f1f1e8', dark: '#1c1b19' };

function applyTheme(next: Theme) {
  document.documentElement.classList.toggle('dark', next === 'dark');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[next]);
  listeners.forEach((notify) => notify());
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, currentDomTheme);

  useEffect(() => {
    // Cross-tab: another tab persisted a new theme.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_KEY) return;
      if (e.newValue === 'dark' || e.newValue === 'light') applyTheme(e.newValue);
    };
    window.addEventListener('storage', onStorage);

    // Follow live OS theme changes until the user sets an explicit preference.
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onMqChange = (e: MediaQueryListEvent) => {
      if (hasExplicitPreference()) return;
      applyTheme(e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', onMqChange);

    return () => {
      window.removeEventListener('storage', onStorage);
      mq.removeEventListener('change', onMqChange);
    };
  }, []);

  const toggleTheme = useCallback(() => {
    const next: Theme = currentDomTheme() === 'dark' ? 'light' : 'dark';
    explicitPreferenceThisSession = true;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // storage blocked or full: the theme still applies for this session
    }
    applyTheme(next);
  }, []);

  return { theme, toggleTheme };
}

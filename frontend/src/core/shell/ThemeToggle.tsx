import { IconMoon, IconSun } from '../../shared/icons';
import { useTheme } from '../theme/useTheme';

/** Light/dark switch. The theme itself is CSS; the hook only toggles `.dark` on <html>. */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button type="button" onClick={toggleTheme}
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-sf-line-strong bg-transparent text-sf-ink-mute hover:bg-sf-hover">
      {theme === 'dark' ? <IconSun size={16} aria-hidden /> : <IconMoon size={16} aria-hidden />}
    </button>
  );
}

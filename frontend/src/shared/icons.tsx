import type { ComponentType, CSSProperties, ReactNode } from 'react';

export interface IconProps {
  size?: number;
  className?: string;
  strokeWidth?: number;
  style?: CSSProperties;
  /**
   * Hide a decorative icon from assistive tech (the usual case inside a labelled control).
   * Forwarded explicitly: `Ico` does not spread rest props, and TypeScript does not check
   * hyphenated JSX attributes, so an unforwarded `aria-hidden` would vanish silently.
   */
  'aria-hidden'?: boolean | 'true' | 'false';
}

function Ico({ size = 18, strokeWidth = 1.75, className, style, children, 'aria-hidden': ariaHidden }: IconProps & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
         className={className} style={{ flexShrink: 0, ...style }} aria-hidden={ariaHidden}>
      {children}
    </svg>
  );
}

// Glyphs are drawn here from plain geometry rather than copied from an icon set, so the repo
// carries no third-party artwork. Add a glyph here before reaching for an icon package.
export function IconPlus(p: IconProps) { return <Ico {...p}><path d="M12 5v14M5 12h14" /></Ico>; }
export function IconX(p: IconProps) { return <Ico {...p}><path d="M18 6 6 18M6 6l12 12" /></Ico>; }
export function IconCheck(p: IconProps) { return <Ico {...p}><path d="M20 6 9 17l-5-5" /></Ico>; }
export function IconMenu(p: IconProps) { return <Ico {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Ico>; }
export function IconChevronDown(p: IconProps) { return <Ico {...p}><path d="m6 9 6 6 6-6" /></Ico>; }
export function IconArrowLeft(p: IconProps) { return <Ico {...p}><path d="M19 12H5M11 18l-6-6 6-6" /></Ico>; }
export function IconHome(p: IconProps) { return <Ico {...p}><path d="M3 11.5 12 4l9 7.5M5.5 9.5V20h13V9.5" /></Ico>; }
export function IconGrid(p: IconProps) { return <Ico {...p}><rect x="4" y="4" width="7" height="7" rx="1" /><rect x="13" y="4" width="7" height="7" rx="1" /><rect x="4" y="13" width="7" height="7" rx="1" /><rect x="13" y="13" width="7" height="7" rx="1" /></Ico>; }
export function IconSliders(p: IconProps) { return <Ico {...p}><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="2" /><circle cx="15" cy="17" r="2" /></Ico>; }
export function IconBell(p: IconProps) { return <Ico {...p}><path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5h4" /></Ico>; }
export function IconSun(p: IconProps) { return <Ico {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></Ico>; }
export function IconMoon(p: IconProps) { return <Ico {...p}><path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" /></Ico>; }
export function IconUser(p: IconProps) { return <Ico {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" /></Ico>; }
export function IconUsers(p: IconProps) { return <Ico {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="17" cy="9" r="2.5" /><path d="M16.5 14a5 5 0 0 1 5 5" /></Ico>; }
export function IconBuilding(p: IconProps) { return <Ico {...p}><rect x="5" y="3" width="14" height="18" rx="1" /><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10.5 21v-3h3v3" /></Ico>; }
export function IconFlask(p: IconProps) { return <Ico {...p}><path d="M9 3h6M10 3v6.5L4.8 18.6A1.6 1.6 0 0 0 6.2 21h11.6a1.6 1.6 0 0 0 1.4-2.4L14 9.5V3M7.5 15h9" /></Ico>; }
export function IconCheckSquare(p: IconProps) { return <Ico {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="2" /><path d="m8 12.5 3 3 5-6" /></Ico>; }
export function IconCalendar(p: IconProps) { return <Ico {...p}><rect x="3.5" y="5" width="17" height="15.5" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4" /></Ico>; }
export function IconMail(p: IconProps) { return <Ico {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 6.5 8.5 6.5 8.5-6.5" /></Ico>; }
export function IconChart(p: IconProps) { return <Ico {...p}><path d="M4 4v16h16M8 16v-3M12 16V9M16 16V6" /></Ico>; }
export function IconFile(p: IconProps) { return <Ico {...p}><path d="M14 3H6.5v18h11V6.5zM14 3v3.5h3.5" /></Ico>; }
export function IconBook(p: IconProps) { return <Ico {...p}><path d="M5 4.5h10a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10" /></Ico>; }
export function IconInbox(p: IconProps) { return <Ico {...p}><path d="M4 13.5h4.5l1.5 2.5h4l1.5-2.5H20M6.5 5h11L20 13.5V19H4v-5.5z" /></Ico>; }
export function IconTarget(p: IconProps) { return <Ico {...p}><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="0.8" /></Ico>; }

/**
 * The manifest `icon` is a short name (`flask`, `users`, `check-square`, ...). Unknown names fall
 * back to a generic tile glyph rather than failing, so an app can name an icon before it exists.
 */
const APP_ICONS: Record<string, ComponentType<IconProps>> = {
  flask: IconFlask, users: IconUsers, user: IconUser, 'check-square': IconCheckSquare,
  building: IconBuilding, calendar: IconCalendar, mail: IconMail, chart: IconChart,
  file: IconFile, book: IconBook, inbox: IconInbox, target: IconTarget, home: IconHome,
  settings: IconSliders, bell: IconBell, grid: IconGrid,
};

export function appIcon(name: string): ComponentType<IconProps> {
  return APP_ICONS[name] ?? IconGrid;
}

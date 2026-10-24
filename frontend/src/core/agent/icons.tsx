import { Ico, type IconProps } from '../../shared/icons';

// Whisk's own glyphs, drawn from plain geometry in the shared icon style.
export function IconSparkle(p: IconProps) { return <Ico {...p}><path d="M11 4c.7 4.4 2.6 6.3 7 7-4.4.7-6.3 2.6-7 7-.7-4.4-2.6-6.3-7-7 4.4-.7 6.3-2.6 7-7zM18.5 3v4M16.5 5h4" /></Ico>; }
export function IconPencil(p: IconProps) { return <Ico {...p}><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" /></Ico>; }
export function IconLock(p: IconProps) { return <Ico {...p}><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></Ico>; }
export function IconTrash(p: IconProps) { return <Ico {...p}><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13" /></Ico>; }
export function IconArrowUp(p: IconProps) { return <Ico {...p}><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" /></Ico>; }
export function IconStop(p: IconProps) { return <Ico {...p}><rect x="6.5" y="6.5" width="11" height="11" rx="1.5" /></Ico>; }

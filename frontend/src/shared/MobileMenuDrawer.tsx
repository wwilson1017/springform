import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { IconX } from './icons';

export interface DrawerItem {
  to: string;
  label: string;
  /** An icon element, sized 18. */
  icon: ReactNode;
}

interface Props {
  items: DrawerItem[];
  onClose: () => void;
  onSignOut?: () => void;
  children?: ReactNode;
}

/** Full-screen navigation for narrow screens. The caller decides which items a user may see. */
export function MobileMenuDrawer({ items, onClose, onSignOut, children }: Props) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Menu" className="fixed inset-0 z-50 flex flex-col bg-sf-card">
      <div className="flex items-center justify-between border-b border-sf-line px-4 py-3">
        <span className="font-display text-xl text-sf-ink">Menu</span>
        <button type="button" onClick={onClose} aria-label="Close menu"
          className="cursor-pointer border-0 bg-transparent p-1 text-sf-ink-mute">
          <IconX aria-hidden />
        </button>
      </div>
      <nav className="flex flex-col gap-0.5 px-4 py-3">
        {items.map(item => (
          <Link key={item.to} to={item.to} onClick={onClose}
            className="flex items-center gap-2.5 rounded px-2 py-3 text-sm text-sf-ink no-underline hover:text-sf-accent-text">
            {item.icon}
            {item.label}
          </Link>
        ))}
        {onSignOut && (
          <button type="button" onClick={() => { onClose(); onSignOut(); }}
            className="cursor-pointer rounded border-0 bg-transparent px-2 py-3 text-left font-sans text-sm text-sf-ink hover:text-sf-accent-text">
            Sign out
          </button>
        )}
      </nav>
      {children}
    </div>
  );
}

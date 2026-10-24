import { useState } from 'react';
import { Link } from 'react-router';
import type { User } from '../api/types';
import { IconChevronDown } from '../../shared/icons';

/** The signed-in user's name; opens to their email and role, Settings and Sign out. */
export function UserMenu({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <div className="relative" onKeyDown={e => { if (e.key === 'Escape') close(); }}>
      <button type="button" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(o => !o)}
        className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-sf-line-strong bg-transparent px-3 font-sans text-sm text-sf-ink-mute hover:bg-sf-hover">
        {user.name}
        <IconChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <>
          {/* A click anywhere outside the menu closes it. */}
          <div className="fixed inset-0 z-10" onClick={close} />
          <div role="menu" className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-sf-line-strong bg-sf-card p-1 shadow-lg">
            <div className="px-3 py-2">
              <div className="truncate text-sm text-sf-ink">{user.email}</div>
              <div className="text-xs text-sf-ink-dim">{user.role === 'admin' ? 'Admin' : 'Member'}</div>
            </div>
            <Link role="menuitem" to="/settings" onClick={close}
              className="block rounded px-3 py-2 text-sm text-sf-ink no-underline hover:bg-sf-hover">Settings</Link>
            <button role="menuitem" type="button" onClick={() => { close(); onSignOut(); }}
              className="block w-full cursor-pointer rounded border-0 bg-transparent px-3 py-2 text-left font-sans text-sm text-sf-ink hover:bg-sf-hover">
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

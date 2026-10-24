/**
 * Admins manage accounts: invite (a one-hour link, mailed when mail is set up and always shown
 * to copy), resend, a password reset link for someone else, edit name/role/time zone, deactivate
 * and reactivate. There is no delete: a
 * departed person's name keeps rendering on what they touched. The server keeps one active admin
 * who can sign in (`last_admin`); the card only hides the controls that would lock you out.
 */

import { useState, type FormEvent } from 'react';
import { patchJson, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import type { Role } from '../api/types';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { useAuth } from './AuthContext';
import {
  alertText, btnDanger, btnLink, btnPrimary, btnSecondary, errorText, inputSm, labelSm, noteText,
  type AdminUser, type InviteLink, type ResetLink,
} from './api';
import { CopyField, TimezoneSelect } from './fields';

const USER_ERRORS = {
  last_admin: 'The install needs at least one active admin who can sign in. Make someone else an admin first.',
  not_found: 'That account no longer exists. Reload the list.',
  invite_accepted: 'They have already accepted their invite.',
  user_inactive: 'Reactivate the account before sending a new invite.',
};

const chip = 'rounded bg-sf-ink/6 px-1.5 py-0.5 text-xs text-sf-ink-dim';

export default function UsersCard() {
  const [status, setStatus] = useState<'active' | 'inactive'>('active');
  const { data: users, error, reload, setData } = useJson<AdminUser[]>(`/api/auth/users?status=${status}`);
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<(InviteLink & { email: string }) | null>(null);

  const replace = (u: AdminUser) => setData((users ?? []).map(x => (x.id === u.id ? u : x)));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Show" className="flex rounded-md border border-sf-line-strong p-0.5">
          {(['active', 'inactive'] as const).map(s => (
            <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)}
              className={`cursor-pointer rounded border-0 px-3 py-1 text-sm ${status === s ? 'bg-sf-raised text-sf-ink' : 'bg-transparent text-sf-ink-soft'}`}>
              {s === 'active' ? 'Active' : 'Inactive'}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {!inviting && <button type="button" className={btnPrimary} onClick={() => { setLink(null); setInviting(true); }}>Invite someone</button>}
      </div>

      {inviting && (
        <InviteForm onCancel={() => setInviting(false)}
          onInvited={(email, l) => { setInviting(false); setLink({ ...l, email }); if (status === 'active') reload(); else setStatus('active'); }} />
      )}
      {link && <LinkPanel link={link} onClose={() => setLink(null)} />}

      {error ? <LoadError label="Couldn't load users" onRetry={reload} compact />
        : !users ? <p className={noteText}>Loading…</p>
        : users.length === 0 ? <p className={noteText}>{status === 'active' ? 'No one yet.' : 'No deactivated accounts.'}</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line border-y border-sf-line p-0">
            {users.map(u => <UserRow key={u.id} user={u} onSaved={replace} onRemoved={reload}
              onLink={l => setLink({ ...l, email: u.email })} />)}
          </ul>
        )}
    </div>
  );
}

function InviteForm({ onInvited, onCancel }: { onInvited: (email: string, link: InviteLink) => void; onCancel: () => void }) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('member');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const r = await postJson<InviteLink & { user: AdminUser }>('/api/auth/users', { email: email.trim(), name: name.trim(), role });
      onInvited(r.user.email, r);
    } catch (err) {
      setError(errorText(err, {}, "Couldn't send the invite."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} aria-label="Invite someone" className="flex flex-col gap-3 rounded-md border border-sf-line-strong bg-sf-raised p-4">
      <div className="grid gap-3 md:grid-cols-[2fr_2fr_1fr]">
        <div>
          <label htmlFor="invite-email" className={labelSm}>Email</label>
          <input id="invite-email" type="email" autoComplete="off" autoFocus value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com" className={inputSm} />
        </div>
        <div>
          <label htmlFor="invite-name" className={labelSm}>Name</label>
          <input id="invite-name" autoComplete="off" value={name} onChange={e => setName(e.target.value)} className={inputSm} />
        </div>
        <div>
          <label htmlFor="invite-role" className={labelSm}>Role</label>
          <select id="invite-role" value={role} onChange={e => setRole(e.target.value as Role)} className={inputSm}>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      </div>
      <p className="m-0 text-xs text-sf-ink-dim">Admins also manage users, sign-in and install settings.</p>
      {error && <p role="alert" className={alertText}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !email.trim()} className={btnPrimary}>{busy ? 'Inviting…' : 'Send invite'}</button>
        <button type="button" className={btnSecondary} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function LinkPanel({ link, onClose }: { link: InviteLink & { email: string }; onClose: () => void }) {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-md border border-sf-green bg-sf-card p-4">
      <p className="m-0 text-sm text-sf-ink">
        {link.mailed
          ? <>Invite emailed to <strong>{link.email}</strong>. You can also send them this link.</>
          : <>Email isn't set up on this install, so send <strong>{link.email}</strong> this link yourself.</>}
        {' '}It works once, for an hour.
      </p>
      <CopyField label="Invite link" value={link.invite_url} />
      <button type="button" className={`${btnLink} self-start`} onClick={onClose}>Done</button>
    </div>
  );
}

function UserRow({ user, onSaved, onRemoved, onLink }: {
  user: AdminUser; onSaved: (u: AdminUser) => void; onRemoved: () => void; onLink: (l: InviteLink) => void;
}) {
  const { user: me } = useAuth();
  const self = me?.id === user.id;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reset, setReset] = useState<ResetLink | null>(null);

  async function act<T>(fn: () => Promise<T>, fallback: string, codes: Record<string, string> = USER_ERRORS): Promise<T | undefined> {
    setError('');
    setBusy(true);
    try {
      return await fn();
    } catch (err) {
      setError(errorText(err, codes, fallback));
    } finally {
      setBusy(false);
    }
  }

  async function setActive(active: boolean) {
    if (!active && !await confirmDialog({
      title: `Deactivate ${user.name || user.email}`,
      message: 'They are signed out everywhere and can no longer sign in. Their name stays on what they worked on. You can reactivate them later.',
      confirmLabel: 'Deactivate', danger: true,
    })) return;
    const r = await act(() => postJson<AdminUser>(`/api/auth/users/${user.id}/${active ? 'reactivate' : 'deactivate'}`), `Couldn't ${active ? 'reactivate' : 'deactivate'} the account.`);
    if (r) { toast.success(`${r.name || r.email} ${active ? 'reactivated' : 'deactivated'}.`); onRemoved(); }
  }

  async function resend() {
    const r = await act(() => postJson<InviteLink>(`/api/auth/users/${user.id}/resend-invite`), "Couldn't create a new invite link.");
    if (r) onLink(r);
  }

  async function resetLink() {
    setReset(null);
    // A 404 is an account that can't take one (deactivated, or gone since the list loaded).
    const r = await act(() => postJson<ResetLink>(`/api/auth/users/${user.id}/reset-link`), "Couldn't create a reset link.",
      { ...USER_ERRORS, not_found: "This account can't get a reset link. Reload the list." });
    if (r) setReset(r);
  }

  return (
    <li className="py-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 text-sm text-sf-ink">
            <span className="font-medium">{user.name || user.email}</span>
            {self && <span className="text-sf-ink-dim">(you)</span>}
            <span className={chip}>{user.role === 'admin' ? 'Admin' : 'Member'}</span>
            {user.invite_pending && <span className={chip}>Invite pending</span>}
            {user.totp_enabled && <span className={chip}>2FA</span>}
            {user.google_linked && <span className={chip}>Google</span>}
          </div>
          <div className="truncate text-xs text-sf-ink-dim">
            {user.name && <>{user.email} · </>}
            {!user.is_active && user.deactivated_at ? `Deactivated ${formatDate(user.deactivated_at)}`
              : user.last_login_at ? `Last sign-in ${formatDate(user.last_login_at)}` : 'Never signed in'}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {user.is_active && !editing && <button type="button" disabled={busy} className={btnSecondary} onClick={() => { setError(''); setEditing(true); }}>Edit</button>}
          {user.is_active && user.invite_pending && !self && <button type="button" disabled={busy} className={btnSecondary} onClick={() => void resend()}>New invite link</button>}
          {/* A pending invite gets a new invite link instead; a reset is for an account already set up. */}
          {user.is_active && !user.invite_pending && !self && <button type="button" disabled={busy} className={btnSecondary} onClick={() => void resetLink()}>Reset link</button>}
          {!self && (user.is_active
            ? <button type="button" disabled={busy} className={btnDanger} onClick={() => void setActive(false)}>Deactivate</button>
            : <button type="button" disabled={busy} className={btnSecondary} onClick={() => void setActive(true)}>Reactivate</button>)}
        </div>
      </div>
      {editing && (
        <EditForm user={user} self={self} busy={busy} onCancel={() => { setError(''); setEditing(false); }}
          onSave={async changes => {
            const r = await act(() => patchJson<AdminUser>(`/api/auth/users/${user.id}`, changes), "Couldn't save the changes.");
            if (r) { onSaved(r); setEditing(false); }
          }} />
      )}
      {reset && (
        <div role="status" className="mt-3 flex flex-col gap-2 rounded-md border border-sf-green bg-sf-card p-3">
          <p className="m-0 text-sm text-sf-ink">
            Password reset link for <strong>{user.name || user.email}</strong>. It works once, for an hour.{reset.mailed && ' Sent by email too.'}
          </p>
          <CopyField label="Reset link" value={reset.reset_url} />
          <button type="button" className={`${btnLink} self-start`} onClick={() => setReset(null)}>Done</button>
        </div>
      )}
      {error && <p role="alert" className={`${alertText} mt-2`}>{error}</p>}
    </li>
  );
}

function EditForm({ user, self, busy, onSave, onCancel }: {
  user: AdminUser; self: boolean; busy: boolean;
  onSave: (changes: { name: string; role: Role; tz: string | null }) => Promise<void>; onCancel: () => void;
}) {
  const [name, setName] = useState(user.name);
  const [role, setRole] = useState<Role>(user.role);
  const [tz, setTz] = useState(user.tz ?? '');
  const id = (f: string) => `user-${user.id}-${f}`;
  return (
    <form onSubmit={e => { e.preventDefault(); void onSave({ name: name.trim(), role, tz: tz || null }); }}
      className="mt-3 grid gap-3 rounded-md bg-sf-raised p-3 md:grid-cols-[2fr_1fr_2fr_auto] md:items-end">
      <div>
        <label htmlFor={id('name')} className={labelSm}>Name</label>
        <input id={id('name')} value={name} onChange={e => setName(e.target.value)} className={inputSm} />
      </div>
      <div>
        <label htmlFor={id('role')} className={labelSm}>Role</label>
        {/* Your own role is another admin's to change: demoting yourself is a one-way door. */}
        <select id={id('role')} value={role} disabled={self} title={self ? 'Another admin can change your role.' : undefined}
          onChange={e => setRole(e.target.value as Role)} className={inputSm}>
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <div>
        <label htmlFor={id('tz')} className={labelSm}>Time zone</label>
        <TimezoneSelect id={id('tz')} value={tz} onChange={setTz} />
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={btnPrimary}>Save</button>
        <button type="button" className={btnSecondary} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

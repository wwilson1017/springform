import { useState, type FormEvent } from 'react';
import { patchJson } from '../api/client';
import { toast } from '../../shared/toast';
import { useAuth } from './AuthContext';
import { alertText, btnPrimary, errorText, inputSm, labelSm } from './api';
import { TimezoneSelect } from './fields';

/** The signed-in user's name and time zone (PATCH /api/me). Email and role are an admin's to change. */
export default function ProfileCard() {
  const { user, refresh } = useAuth();
  const [name, setName] = useState(user?.name ?? '');
  const [tz, setTz] = useState(user?.tz ?? '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  const dirty = name.trim() !== user.name || tz !== (user.tz ?? '');

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await patchJson('/api/me', { name: name.trim(), tz: tz || null });
      await refresh();
      toast.success('Profile saved.');
    } catch (err) {
      setError(errorText(err, {}, "Couldn't save your profile."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
      <div>
        <p className={labelSm}>Email</p>
        <p className="m-0 break-all text-sm text-sf-ink">{user.email} <span className="text-sf-ink-dim">· {user.role === 'admin' ? 'Admin' : 'Member'}</span></p>
      </div>
      <div>
        <label htmlFor="profile-name" className={labelSm}>Name</label>
        <input id="profile-name" value={name} onChange={e => setName(e.target.value)} autoComplete="name" className={inputSm} />
      </div>
      <div>
        <label htmlFor="profile-tz" className={labelSm}>Time zone</label>
        <TimezoneSelect id="profile-tz" value={tz} onChange={setTz} />
      </div>
      {error && <p role="alert" className={alertText}>{error}</p>}
      <div>
        <button type="submit" disabled={busy || !dirty || !name.trim()} className={btnPrimary}>{busy ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  );
}

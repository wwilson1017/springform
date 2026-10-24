import type { UserRef } from '../../../core/api/types';
import { input } from '../ui';

/** Owner is an assignment and a filter, never a permission; `null` is a real state (unassigned). */
export function OwnerSelect({ id, value, onChange, users, currentName }: {
  id: string;
  value: number | null;
  onChange: (value: number | null) => void;
  users: UserRef[];
  /** The deal's owner name, so an owner outside the user list still reads correctly. */
  currentName?: string | null;
}) {
  const known = value === null || users.some(u => u.id === value);
  return (
    <select id={id} value={value ?? ''} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)} className={input}>
      <option value="">Unassigned</option>
      {!known && <option value={value!}>{currentName ?? `User ${value}`}</option>}
      {users.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
    </select>
  );
}

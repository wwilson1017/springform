import type { UserRef } from '../api/types';
import type { Draft } from './fieldValues';
import type { FieldDefinition } from './types';
import { INPUT } from './ui';

/** The editor for one custom field, chosen by its type. `id` labels the control. */
export function FieldInput({ def, draft, onChange, users, id, disabled }: {
  def: FieldDefinition;
  draft: Draft;
  onChange: (next: Draft) => void;
  users: UserRef[];
  id: string;
  disabled?: boolean;
}) {
  const text = typeof draft === 'string' ? draft : '';
  const common = { id, disabled, className: INPUT };
  switch (def.type) {
    case 'number':
      // step="any": the server takes any finite number, so a fraction must not fail native validation.
      return <input {...common} type="number" step="any" value={text} onChange={e => onChange(e.target.value)} />;
    case 'date':
      return <input {...common} type="date" value={text} onChange={e => onChange(e.target.value)} />;
    case 'url':
      return <input {...common} type="url" placeholder="https://" value={text} onChange={e => onChange(e.target.value)} />;
    case 'boolean':
      return (
        <select {...common} value={text} onChange={e => onChange(e.target.value)}>
          <option value="">—</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      );
    case 'select':
      return (
        <select {...common} value={text} onChange={e => onChange(e.target.value)}>
          <option value="">—</option>
          {/* A value whose option was since removed stays visible rather than silently changing. */}
          {[...(def.options ?? []), ...(text && !def.options?.includes(text) ? [text] : [])].map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case 'user':
      return (
        <select {...common} value={text} onChange={e => onChange(e.target.value)}>
          <option value="">—</option>
          {users.map(u => <option key={u.id} value={String(u.id)}>{u.name}</option>)}
          {text && !users.some(u => String(u.id) === text) && <option value={text}>User #{text}</option>}
        </select>
      );
    case 'multiselect': {
      const picked = Array.isArray(draft) ? draft : [];
      return (
        <div id={id} role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap gap-x-4 gap-y-1">
          {(def.options ?? []).map(o => (
            <label key={o} className="flex items-center gap-1.5 text-sm text-sf-ink">
              <input type="checkbox" disabled={disabled} checked={picked.includes(o)} className="accent-sf-accent"
                onChange={e => onChange(e.target.checked ? [...picked, o] : picked.filter(p => p !== o))} />
              {o}
            </label>
          ))}
        </div>
      );
    }
    default:
      return <input {...common} type="text" value={text} onChange={e => onChange(e.target.value)} />;
  }
}

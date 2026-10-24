// Who sees a row and who it is for: the visibility toggle and the assignee picker that todos,
// projects and areas share, and the chip a team row shows on a list. The server owns the rules
// (only the owner makes a row private; a private row's assignee is nobody or its owner; a child
// sits only under a parent everyone who sees it can see) and answers a refusal with a sentence,
// which the form shows; the picker only leaves out what can never be saved.
import { IconUsers } from '../../../shared/icons';
import type { Member, Visibility } from '../types';
import { memberName } from '../util';

const inputCls =
  'w-full rounded-lg border border-sf-line-strong bg-sf-card px-3 py-2 text-base sm:text-sm text-sf-ink focus:border-sf-accent focus:outline-none disabled:opacity-50';
const labelCls = 'block text-xs font-display font-semibold text-sf-ink-dim mb-1';

export interface SharingPatch {
  visibility?: Visibility;
  assignee_user_id?: number | null;
}

interface FieldsProps {
  /** Distinguishes several forms on one page (`${idPrefix}-visibility`). */
  idPrefix: string;
  visibility: Visibility;
  assignee: number | null;
  /** The row's owner (the caller, for a new row): a private row may be assigned only to them. */
  ownerId: number | null;
  members: Member[];
  /** One change, as the PATCH fields it takes. */
  onChange: (patch: SharingPatch) => void;
  disabled?: boolean;
  /** Lay the two fields out side by side (the edit sheet's grid) rather than stacked. */
  inline?: boolean;
}

/** Private / Team, then the assignee. Making a row private drops an assignee who is not its
 *  owner in the same change, since the server would refuse the pair. */
export function SharingFields({
  idPrefix, visibility, assignee, ownerId, members, onChange, disabled, inline,
}: FieldsProps) {
  const choices = visibility === 'private' ? members.filter(m => m.id === ownerId) : members;
  // The current assignee always has an option, even once deactivated.
  const listed = assignee !== null && !choices.some(m => m.id === assignee)
    ? [{ id: assignee, name: memberName(members, assignee)! }, ...choices] : choices;
  return (
    <div className={inline ? 'contents' : 'grid gap-3 sm:grid-cols-2'}>
      <div>
        <span className={labelCls} id={`${idPrefix}-visibility`}>Who can see it</span>
        <div role="radiogroup" aria-labelledby={`${idPrefix}-visibility`} className="flex rounded-lg border border-sf-line-strong bg-sf-card p-0.5">
          {(['private', 'team'] as const).map(v => (
            <button key={v} type="button" role="radio" aria-checked={visibility === v} disabled={disabled}
              onClick={() => {
                if (v === visibility) return;
                onChange(v === 'private' && assignee !== null && assignee !== ownerId
                  ? { visibility: v, assignee_user_id: null } : { visibility: v });
              }}
              className={`flex-1 cursor-pointer rounded-md border-0 px-3 py-1.5 text-sm disabled:cursor-default disabled:opacity-50 ${
                visibility === v ? 'bg-sf-raised font-semibold text-sf-ink' : 'bg-transparent text-sf-ink-dim hover:text-sf-ink'}`}>
              {v === 'private' ? 'Only me' : 'Team'}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className={labelCls} htmlFor={`${idPrefix}-assignee`}>Assigned to</label>
        <select id={`${idPrefix}-assignee`} className={inputCls} disabled={disabled}
          value={assignee ?? ''} onChange={e => onChange({ assignee_user_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Nobody</option>
          {listed.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
      </div>
    </div>
  );
}

/** A team row's chip on a list: who owns it and who it is for. Private rows show none: only
 *  their owner ever sees them. */
export function TeamChip({ visibility, ownerName, assigneeName }: {
  visibility: Visibility;
  ownerName: string | null;
  assigneeName: string | null;
}) {
  if (visibility !== 'team') return null;
  const text = `Team${ownerName ? ` · ${ownerName}` : ''}${assigneeName ? ` → ${assigneeName}` : ''}`;
  return (
    <span data-team className="inline-flex items-center gap-1 rounded-full bg-sf-ai/15 px-2 py-0.5 text-sf-ai-text"
      title={`Team: everyone can see and edit it.${ownerName ? ` Owner: ${ownerName}.` : ''} ${assigneeName ? `Assigned to ${assigneeName}.` : 'Unassigned.'}`}>
      <IconUsers size={12} aria-hidden />
      {text}
    </span>
  );
}

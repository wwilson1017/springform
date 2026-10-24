import { UserPicker } from '../../../shared/UserPicker';
import { input } from '../ui';

/** Owner is an assignment and a filter, never a permission; `null` is a real state (unassigned). */
export function OwnerSelect({ id, value, onChange, currentName }: {
  id: string;
  value: number | null;
  onChange: (value: number | null) => void;
  /** The stored owner's name, so it reads correctly before any search. */
  currentName?: string | null;
}) {
  return (
    <UserPicker id={id} className={input} value={value === null ? '' : String(value)} valueName={currentName}
      onChange={v => onChange(v ? Number(v) : null)} options={[['', 'Unassigned']]} />
  );
}

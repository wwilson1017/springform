/**
 * Mark Won asks which day it actually closed: default today, earlier days allowed, a future day
 * refused (typing bypasses the input's `max`, hence the explicit check). The server refuses a
 * day after the install's today.
 */
import { useRef, useState } from 'react';
import { closedOnIsValid, ymd } from '../closedOn';
import { btnPrimary, btnSecondary, input, label } from '../ui';
import { Dialog } from './Dialog';

export function ClosedOnDialog({ dealTitle, onConfirm, onCancel }: {
  dealTitle: string;
  /** Called at most once with the chosen `YYYY-MM-DD`. */
  onConfirm: (closedOn: string) => void;
  onCancel: () => void;
}) {
  const [today] = useState(() => ymd(new Date()));
  const [day, setDay] = useState(today);
  const submitted = useRef(false);
  const valid = closedOnIsValid(day, today);

  function confirm() {
    if (submitted.current || !valid) return;
    submitted.current = true;
    onConfirm(day);
  }

  return (
    <Dialog title="When did this close?" subtitle={dealTitle} onClose={onCancel}>
      <label htmlFor="crm-closed-on" className={label}>Closed on</label>
      <input id="crm-closed-on" type="date" value={day} max={today} required className={input}
        onChange={e => setDay(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); confirm(); } }} />
      {day > today && <p role="alert" className="m-0 mt-1.5 text-xs text-sf-red-text">Closed on cannot be in the future.</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={btnSecondary}>Cancel</button>
        <button type="button" onClick={confirm} disabled={!valid} className={btnPrimary}>Mark won</button>
      </div>
    </Dialog>
  );
}

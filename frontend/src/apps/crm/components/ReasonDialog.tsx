/**
 * Mark Lost asks why (optional); Archive asks why (required: the server refuses a blank one).
 * Cmd/Ctrl+Enter submits; it submits at most once.
 */
import { useRef, useState } from 'react';
import { MAX_REASON } from '../constants';
import { btnDanger, btnPrimary, btnSecondary, input, label } from '../ui';
import { Dialog } from './Dialog';

export function ReasonDialog({ dealTitle, variant, onConfirm, onCancel }: {
  dealTitle: string;
  variant: 'lost' | 'archive';
  /** Called at most once with the typed reason (`''` when Mark Lost is left blank). */
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('');
  const submitted = useRef(false);
  const archive = variant === 'archive';
  const blocked = archive && reason.trim() === '';

  function confirm() {
    if (submitted.current || blocked) return;
    submitted.current = true;
    onConfirm(reason.trim());
  }

  return (
    <Dialog title={archive ? 'Archive deal' : 'Mark as lost'} subtitle={dealTitle} onClose={onCancel}>
      <label htmlFor="crm-reason" className={label}>{archive ? 'Why archive? (required)' : 'Reason (optional)'}</label>
      <textarea
        id="crm-reason"
        value={reason}
        onChange={e => setReason(e.target.value)}
        onKeyDown={e => {
          // An IME uses Enter to commit a candidate; that Enter is not a submit.
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.altKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            confirm();
          }
        }}
        rows={3}
        maxLength={MAX_REASON}
        placeholder={archive ? 'e.g. Entered twice, created by mistake' : 'e.g. Budget moved, chose a competitor'}
        className={`${input} resize-y`}
      />
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
        <span className="mr-auto text-xs text-sf-ink-dim">Cmd/Ctrl+Enter to submit</span>
        <button type="button" onClick={onCancel} className={btnSecondary}>Cancel</button>
        <button type="button" onClick={confirm} disabled={blocked} className={archive ? btnPrimary : btnDanger}>
          {archive ? 'Archive' : 'Mark lost'}
        </button>
      </div>
    </Dialog>
  );
}

/**
 * New deal. Person and organization are picked separately from the shared directory; the
 * Deals panel on a person or organization page opens this with that record pre-linked.
 */
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../../core/api/client';
import { useAuth } from '../../../core/auth/AuthContext';
import { ContactPicker } from '../../../core/contacts/ContactPicker';
import { createDeal, type Deal, type Stage } from '../api';
import { STAGE_ORDER, stageLabel } from '../constants';
import { inputToCents } from '../money';
import { btnPrimary, btnSecondary, input, label } from '../ui';
import { Dialog } from './Dialog';
import { OwnerSelect } from './OwnerSelect';

type Ref = { id: number; name: string };

export function DealForm({ person, organization, onClose, onCreated }: {
  person?: Ref | null;
  organization?: Ref | null;
  onClose: () => void;
  onCreated: (deal: Deal) => void;
}) {
  const { user } = useAuth();
  const [title, setTitle] = useState('');
  const [stage, setStage] = useState<Stage>('lead');
  const [value, setValue] = useState('');
  const [probability, setProbability] = useState('');
  const [expectedClose, setExpectedClose] = useState('');
  const [personRef, setPersonRef] = useState<Ref | null>(person ?? null);
  const [orgRef, setOrgRef] = useState<Ref | null>(organization ?? null);
  const [owner, setOwner] = useState<number | null>(user?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cents = inputToCents(value);
    if (!title.trim()) return setError('A title is required.');
    if (cents === null) return setError('Value must be an amount, like 4800 or 4,800.50.');
    const prob = probability === '' ? 0 : Number(probability);
    if (!Number.isInteger(prob) || prob < 0 || prob > 100) return setError('Probability is a whole number from 0 to 100.');
    setBusy(true);
    setError('');
    try {
      onCreated(await createDeal({
        title: title.trim(), stage, value_cents: cents, probability: prob,
        expected_close: expectedClose || null, person_id: personRef?.id ?? null,
        organization_id: orgRef?.id ?? null, owner_user_id: owner,
      }));
    } catch (err) {
      setError(err instanceof ApiError && err.status < 500 ? err.detail : "Couldn't create the deal.");
      setBusy(false);
    }
  }

  return (
    <Dialog title="New deal" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        {error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}
        <div>
          <label htmlFor="deal-title" className={label}>Title</label>
          <input id="deal-title" value={title} onChange={e => setTitle(e.target.value)} maxLength={200} className={input} />
        </div>
        <div>
          <span className={label}>Person</span>
          <ContactPicker kind="person" value={personRef} onChange={setPersonRef} allowCreate placeholder="Link a person" />
        </div>
        <div>
          <span className={label}>Organization</span>
          <ContactPicker kind="organization" value={orgRef} onChange={setOrgRef} allowCreate placeholder="Link an organization" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="deal-stage" className={label}>Stage</label>
            <select id="deal-stage" value={stage} onChange={e => setStage(e.target.value as Stage)} className={input}>
              {STAGE_ORDER.map(s => <option key={s} value={s}>{stageLabel(s)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="deal-value" className={label}>Value</label>
            <input id="deal-value" inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} placeholder="0" className={input} />
          </div>
          <div>
            <label htmlFor="deal-probability" className={label}>Probability (%)</label>
            <input id="deal-probability" type="number" min={0} max={100} value={probability} onChange={e => setProbability(e.target.value)} className={input} />
          </div>
          <div>
            <label htmlFor="deal-close" className={label}>Expected close</label>
            <input id="deal-close" type="date" value={expectedClose} onChange={e => setExpectedClose(e.target.value)} className={input} />
          </div>
        </div>
        <div>
          <label htmlFor="deal-owner" className={label}>Owner</label>
          <OwnerSelect id="deal-owner" value={owner} onChange={setOwner} currentName={user?.name} />
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary}>{busy ? 'Creating…' : 'Create deal'}</button>
        </div>
      </form>
    </Dialog>
  );
}

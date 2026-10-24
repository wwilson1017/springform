/**
 * The CRM's settings card (admins only, per the manifest): when a deal counts as stale, whether
 * the AI counts touches, the default currency for new deals, the stage criteria, and the reset
 * that empties the CRM (deals and activity; people and organizations stay).
 */
import { useState } from 'react';
import { ApiError } from '../../core/api/client';
import { useJson } from '../../core/api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { resetCrm, saveSettings, settingsUrl, type CrmSettings } from './api';
import { StageCriteriaEditor } from './components/StageCriteriaEditor';
import { btnDanger, btnPrimary, field, input, label, muted } from './ui';
import './theme.css';

export default function CrmSettingsCard() {
  const { data, error, reload, setData } = useJson<CrmSettings>(settingsUrl);
  if (error) return <LoadError label="Couldn't load the CRM settings" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  return (
    <div className="flex flex-col gap-6">
      <SettingsForm key={JSON.stringify(data)} settings={data} onSaved={setData} />
      <div>
        <h3 className="m-0 mb-1 text-sm font-medium text-sf-ink">Stage criteria</h3>
        <p className="m-0 mb-2 text-xs text-sf-ink-mute">What a deal should show to enter each stage. Everyone sees them on the board.</p>
        <StageCriteriaEditor />
      </div>
      <ResetCrm />
    </div>
  );
}

function SettingsForm({ settings, onSaved }: { settings: CrmSettings; onSaved: (s: CrmSettings) => void }) {
  const [stale, setStale] = useState(String(settings.stale_days));
  const [touch, setTouch] = useState(settings.touch_count_enabled);
  const [currency, setCurrency] = useState(settings.default_currency);
  const [busy, setBusy] = useState(false);
  const days = Number(stale);
  const validDays = Number.isInteger(days) && days >= 1 && days <= 365;
  const validCurrency = /^[A-Za-z]{3}$/.test(currency.trim());
  const dirty = days !== settings.stale_days || touch !== settings.touch_count_enabled || currency.trim().toUpperCase() !== settings.default_currency;

  async function save() {
    setBusy(true);
    try {
      onSaved(await saveSettings({ stale_days: days, touch_count_enabled: touch, default_currency: currency.trim().toUpperCase() }));
      toast.success('CRM settings saved');
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.detail : "Couldn't save the CRM settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="grid gap-3 md:grid-cols-2" onSubmit={e => { e.preventDefault(); void save(); }}>
      <div>
        <label htmlFor="crm-stale-days" className={label}>Stale after (days)</label>
        <input id="crm-stale-days" type="number" min={1} max={365} value={stale} onChange={e => setStale(e.target.value)} className={input} />
        <p className="m-0 mt-1 text-xs text-sf-ink-dim">An open deal with no activity this long needs a touch.</p>
      </div>
      <div>
        <label htmlFor="crm-currency" className={label}>Default currency</label>
        <input id="crm-currency" value={currency} maxLength={3} onChange={e => setCurrency(e.target.value)} className={`${input} uppercase`} />
      </div>
      <label className="flex items-center gap-2 text-sm text-sf-ink md:col-span-2">
        <input type="checkbox" checked={touch} onChange={e => setTouch(e.target.checked)} className="accent-sf-accent" />
        Count touches with AI (uses the configured AI provider; skipped without one)
      </label>
      <div className="md:col-span-2">
        <button type="submit" disabled={busy || !dirty || !validDays || !validCurrency} className={btnPrimary}>Save</button>
      </div>
    </form>
  );
}

function ResetCrm() {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);

  async function reset() {
    setBusy(true);
    try {
      const out = await resetCrm();
      toast.success(`CRM reset: ${out.deals} deals and ${out.activity} activity entries deleted.`);
      setTyped('');
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.detail : "Couldn't reset the CRM.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-sf-line-strong p-3">
      <h3 className="m-0 mb-1 text-sm font-medium text-sf-red-text">Reset the CRM</h3>
      <p className="m-0 mb-2 text-xs text-sf-ink-mute">
        Deletes every deal and activity entry, with their notes, files and history. People and organizations stay. This cannot be undone.
      </p>
      <div className="flex flex-wrap gap-2">
        <label htmlFor="crm-reset-confirm" className="sr-only">Type RESET to confirm</label>
        <input id="crm-reset-confirm" value={typed} onChange={e => setTyped(e.target.value)} placeholder="Type RESET" autoComplete="off" className={`${field} w-40`} />
        <button type="button" disabled={busy || typed !== 'RESET'} onClick={() => void reset()} className={btnDanger}>Reset CRM</button>
      </div>
    </div>
  );
}

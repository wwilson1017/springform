import { useState } from 'react';
import { btnSecondary, inputSm } from './api';

const ZONES: string[] = Intl.supportedValuesOf('timeZone');

/** IANA time zones; '' means "the install's default". A stored zone the browser doesn't list stays selectable. */
export function TimezoneSelect({ id, value, onChange, disabled }: { id: string; value: string; onChange: (tz: string) => void; disabled?: boolean }) {
  const zones = value && !ZONES.includes(value) ? [value, ...ZONES] : ZONES;
  return (
    <select id={id} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} className={inputSm}>
      <option value="">Install default</option>
      {zones.map(z => <option key={z} value={z}>{z.replaceAll('_', ' ')}</option>)}
    </select>
  );
}

/** Read-only text with a Copy button: invite links, the redirect URI, a 2FA secret. */
export function CopyField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* no clipboard (http, permissions): the text is selectable */ }
  }
  return (
    <div className="flex gap-2">
      <input aria-label={label} readOnly value={value} onFocus={e => e.target.select()}
        className={`${inputSm} min-w-0 flex-1 ${mono ? 'font-mono text-xs' : ''}`} />
      <button type="button" className={`${btnSecondary} shrink-0`} onClick={() => void copy()}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  );
}

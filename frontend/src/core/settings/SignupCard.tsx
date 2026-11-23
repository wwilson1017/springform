import { useState, type FormEvent } from 'react';
import { putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { SETTINGS_URL, type CoreSettings } from './types';
import { buttonClass, errorText, errorTextClass, inputClass, labelClass } from './ui';

const KEY = 'auth.signup_allow';

/** The sign-up allow list (`auth.signup_allow`): `@domain` or `name@domain`, one per line. */
export default function SignupCard() {
  const { data, error, reload, setData } = useJson<CoreSettings>(SETTINGS_URL);
  if (error) return <LoadError label="Couldn't load settings" onRetry={reload} compact />;
  if (!data) return <BootFallback variant="panel" />;
  return <SignupForm settings={data} onSaved={setData} />;
}

function SignupForm({ settings, onSaved }: { settings: CoreSettings; onSaved: (s: CoreSettings) => void }) {
  const [text, setText] = useState(((settings.values[KEY] as string[] | undefined) ?? []).join('\n'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await putJson<CoreSettings>(SETTINGS_URL, { values: { [KEY]: text.split('\n') } });
      setText(((saved.values[KEY] as string[] | undefined) ?? []).join('\n'));
      onSaved(saved);
      toast.success('Sign-up list saved');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <div>
        <label htmlFor="signup-allow" className={labelClass}>
          Domains and addresses, one per line
        </label>
        <textarea
          id="signup-allow"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'@example.com\npat@example.org'}
          className={inputClass}
        />
        <p className="mb-0 mt-1 text-xs text-sf-ink-dim">
          Anyone at a listed domain, or a listed address, can choose "First time here?" on the sign-in page and set up
          their own account as a member. Leave empty to add everyone yourself. Needs email to be configured.
        </p>
      </div>
      {error && (
        <p role="alert" className={errorTextClass}>
          {error}
        </p>
      )}
      <div>
        <button type="submit" disabled={busy} className={buttonClass}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  );
}

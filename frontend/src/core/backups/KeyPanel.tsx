import { useEffect, useState } from 'react';
import { ApiError, postJson } from '../api/client';
import { buttonClass, errorText, errorTextClass, secondaryButtonClass } from '../settings/ui';
import { toast } from '../../shared/toast';
import type { KeyReveal, KeySource } from './types';

type View =
  | { kind: 'hidden' }
  | { kind: 'revealed'; key: string; fingerprint: string }
  | { kind: 'shown' };

/**
 * The encryption key that protects stored credentials. An environment key is never returned,
 * only its fingerprint; a key file's key is shown once, and the server answers 410 after that.
 */
export function KeyPanel({ keySource, keyShown }: { keySource: KeySource; keyShown: boolean }) {
  const [view, setView] = useState<View>({ kind: keyShown ? 'shown' : 'hidden' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reveal() {
    setBusy(true);
    setError(null);
    try {
      const r = await postJson<KeyReveal>('/api/core/backups/key');
      setView(r.key ? { kind: 'revealed', key: r.key, fingerprint: r.fingerprint } : { kind: 'shown' });
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) setView({ kind: 'shown' });
      else setError(errorText(e, "Couldn't fetch the key. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (keySource === 'env') return <EnvKey />;
  return (
    <div className="flex flex-col gap-3 text-sm">
      {view.kind === 'hidden' && (
        <>
          <p className="m-0 text-sf-ink-mute">
            Stored credentials are encrypted with a key kept in the data volume. You can see it here once; keep a copy off-site.
          </p>
          <div><button type="button" onClick={() => void reveal()} disabled={busy} className={buttonClass}>Show key once</button></div>
        </>
      )}
      {view.kind === 'revealed' && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <code data-testid="encryption-key" className="min-w-0 flex-1 select-all break-all rounded-md border border-sf-line-strong bg-sf-raised px-3 py-2 font-mono text-xs text-sf-ink">{view.key}</code>
            <button type="button" className={secondaryButtonClass}
              onClick={() => navigator.clipboard.writeText(view.key).then(() => toast.success('Key copied'), () => toast.error("Couldn't copy; select the key and copy it"))}>
              Copy
            </button>
          </div>
          <Fingerprint value={view.fingerprint} />
          <p className="m-0 font-medium text-sf-amber-text">Store this off-site; without it a restored copy cannot read stored credentials.</p>
        </>
      )}
      {view.kind === 'shown' && (
        <p className="m-0 text-sf-ink-mute">The key was already shown. It stays in the data volume as <code>.encryption-key</code>.</p>
      )}
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
    </div>
  );
}

/** For an environment key POST /key only reports the fingerprint, so it is asked for on mount. */
function EnvKey() {
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  useEffect(() => {
    postJson<KeyReveal>('/api/core/backups/key').then(r => setFingerprint(r.fingerprint), () => {});
  }, []);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="m-0 text-sf-ink-mute">Your key is in your environment; keep it with your .env.</p>
      {fingerprint && <Fingerprint value={fingerprint} />}
    </div>
  );
}

const Fingerprint = ({ value }: { value: string }) => (
  <p className="m-0 text-xs text-sf-ink-dim">Fingerprint <code className="font-mono text-sf-ink-mute">{value}</code></p>
);

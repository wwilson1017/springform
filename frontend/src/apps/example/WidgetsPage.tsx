import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { useJson } from '../../core/api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { createWidget, widgetsUrl, type Widget } from './api';

export function WidgetsPage() {
  const { data: widgets, error, reload } = useJson<Widget[]>(widgetsUrl());
  const [name, setName] = useState('');
  const [color, setColor] = useState('#3a6cb0');
  const [isPrivate, setIsPrivate] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await createWidget({ name: name.trim(), color, is_private: isPrivate });
      setName('');
      setIsPrivate(false);
      reload();
    } catch {
      toast.error("Couldn't create the widget.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
      <h1 className="m-0 mb-1 font-display text-2xl font-medium text-sf-ink">Widgets</h1>
      <p className="mt-0 text-sm text-sf-ink-soft">The example app: a small record type that exercises every platform seam.</p>

      <form onSubmit={onCreate} className="my-6 flex flex-wrap items-center gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4">
        <label htmlFor="widget-name" className="sr-only">Name</label>
        <input id="widget-name" value={name} onChange={e => setName(e.target.value)} placeholder="New widget name"
          className="min-w-40 flex-1 rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim" />
        <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
          Color <input type="color" value={color} onChange={e => setColor(e.target.value)} className="h-8 w-10 cursor-pointer border-0 bg-transparent p-0" />
        </label>
        <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
          <input type="checkbox" checked={isPrivate} onChange={e => setIsPrivate(e.target.checked)} className="accent-sf-accent" />
          Private
        </label>
        <button type="submit" disabled={busy || !name.trim()}
          className="cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink disabled:opacity-50">
          Add widget
        </button>
      </form>

      {error ? <LoadError label="Couldn't load widgets" onRetry={reload} />
        : !widgets ? <p className="text-sm text-sf-ink-dim">Loading…</p>
        : widgets.length === 0 ? <p className="text-sm text-sf-ink-dim">No widgets yet. Add one above.</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
            {widgets.map(w => (
              <li key={w.id}>
                <Link to={String(w.id)} className="flex items-center gap-3 px-4 py-3 text-sf-ink no-underline hover:bg-sf-hover">
                  <span className="h-3 w-3 shrink-0 rounded-full border border-sf-line-strong" style={{ background: w.color ?? 'transparent' }} />
                  <span className="flex-1 text-sm">{w.name}</span>
                  {w.is_private && <span className="rounded bg-sf-ink/6 px-1.5 py-0.5 text-xs text-sf-ink-dim">private</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}

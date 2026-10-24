import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { ApiError } from '../../core/api/client';
import { useJson } from '../../core/api/useJson';
import { Attachments } from '../../core/records/Attachments';
import { Timeline } from '../../core/records/Timeline';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { updateWidget, widgetUrl, type Widget, type WidgetInput, WIDGET_ENTITY } from './api';

export function WidgetPage() {
  const { id } = useParams();
  const { data: widget, error, reload, setData } = useJson<Widget>(widgetUrl(id!));

  if (error instanceof ApiError && error.status === 404) {
    return <Shell><p className="text-sf-ink-mute">This widget doesn't exist, or you can't see it.</p></Shell>;
  }
  if (error) return <Shell><LoadError label="Couldn't load the widget" onRetry={reload} /></Shell>;
  if (!widget) return <Shell><p className="text-sm text-sf-ink-dim">Loading…</p></Shell>;

  async function save(patch: WidgetInput) {
    try {
      setData(await updateWidget(widget!.id, patch));
    } catch {
      toast.error("Couldn't save the widget.");
    }
  }

  return (
    <Shell>
      {/* key: a fresh form when the saved widget changes */}
      <WidgetForm key={widget.updated_at} widget={widget} onSave={save} />
      <div className="mt-8 grid gap-8 md:grid-cols-2">
        <div>
          <h2 className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Timeline</h2>
          {/* Remounts after a save, so the server's field-change entry shows up. */}
          <Timeline key={widget.updated_at} entityType={WIDGET_ENTITY} entityId={widget.id} />
        </div>
        <div>
          <h2 className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Files</h2>
          <Attachments entityType={WIDGET_ENTITY} entityId={widget.id} />
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <Link to=".." relative="path" className="text-sm text-sf-accent-text">← All widgets</Link>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function WidgetForm({ widget, onSave }: { widget: Widget; onSave: (patch: WidgetInput) => Promise<void> }) {
  const [name, setName] = useState(widget.name);
  const [color, setColor] = useState(widget.color ?? '#000000');
  const [busy, setBusy] = useState(false);
  const dirty = name.trim() !== widget.name || color !== (widget.color ?? '#000000');

  async function run(patch: WidgetInput) {
    setBusy(true);
    await onSave(patch);
    setBusy(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor="widget-edit-name" className="sr-only">Name</label>
      <input id="widget-edit-name" value={name} onChange={e => setName(e.target.value)}
        className="min-w-40 flex-1 rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 font-display text-xl text-sf-ink" />
      <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
        Color <input type="color" value={color} onChange={e => setColor(e.target.value)} className="h-8 w-10 cursor-pointer border-0 bg-transparent p-0" />
      </label>
      <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
        <input type="checkbox" checked={widget.is_private} disabled={busy} className="accent-sf-accent"
          onChange={e => void run({ is_private: e.target.checked })} />
        Private
      </label>
      <button type="button" disabled={busy || !dirty || !name.trim()} onClick={() => void run({ name: name.trim(), color })}
        className="cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink disabled:opacity-50">
        Save
      </button>
    </div>
  );
}

// placeholder: replaced by fe-contacts
/**
 * Minimal person/organization picker over GET /api/core/contacts/search, with the props the
 * real picker exposes, so apps that link records typecheck and work before it lands.
 */
import { useEffect, useId, useState } from 'react';
import { fetchJson } from '../api/client';

export interface ContactPickerProps {
  kind: 'person' | 'organization';
  value: { id: number; name: string } | null;
  onChange: (value: { id: number; name: string } | null) => void;
  allowCreate?: boolean;
  placeholder?: string;
  label?: string;
  exclude?: number[];
}

export function ContactPicker({ kind, value, onChange, placeholder, label, exclude }: ContactPickerProps) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Array<{ id: number; name: string }>>([]);
  const id = useId();

  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchJson<Array<{ id: number; name: string }>>(
        `/api/core/contacts/search?${new URLSearchParams({ q, kind, limit: '20' })}`, ctrl.signal,
      ).then(setHits, () => {});
    }, 200);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [query, kind]);

  if (value) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink">
        <span className="flex-1 truncate">{value.name}</span>
        <button type="button" onClick={() => onChange(null)} aria-label={`Clear ${kind}`}
          className="cursor-pointer border-0 bg-transparent p-0 text-xs text-sf-ink-dim">Clear</button>
      </div>
    );
  }
  const shown = query.trim() ? hits.filter(h => !exclude?.includes(h.id)) : [];
  return (
    <div className="relative">
      <input id={id} value={query} onChange={e => setQuery(e.target.value)} placeholder={placeholder ?? `Search ${kind === 'person' ? 'people' : 'organizations'}`}
        aria-label={label ?? placeholder ?? kind}
        className="w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim" />
      {shown.length > 0 && (
        <ul role="listbox" className="absolute z-10 m-0 mt-1 max-h-56 w-full list-none overflow-y-auto rounded-md border border-sf-line-strong bg-sf-card p-0 shadow">
          {shown.map(h => (
            <li key={h.id} role="option" aria-selected={false}>
              <button type="button" onClick={() => { onChange({ id: h.id, name: h.name }); setQuery(''); }}
                className="w-full cursor-pointer border-0 bg-transparent px-3 py-2 text-left text-sm text-sf-ink hover:bg-sf-hover">{h.name}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

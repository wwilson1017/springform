/**
 * Smart import: upload a CSV or vCard, review the people it found (untick any to skip), then
 * create them in the shared directory with their organizations linked. Nothing is saved until
 * Import; the server reads recognisable headers itself and uses the AI only when it must.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { ApiError } from '../../../core/api/client';
import { confirmImport, parseImport, type ImportParsed, type ImportResult } from '../api';
import { btnPrimary, btnSecondary, card, page, pageTitle } from '../ui';

type Step =
  | { kind: 'upload' }
  | { kind: 'parsing' }
  | { kind: 'preview'; parsed: ImportParsed; selected: Set<number> }
  | { kind: 'result'; result: ImportResult };

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError && e.status < 500 ? e.detail : fallback);

export function ImportPage() {
  const [step, setStep] = useState<Step>({ kind: 'upload' });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [importing, setImporting] = useState(false);

  async function parse() {
    if (!file) return;
    setStep({ kind: 'parsing' });
    setError('');
    try {
      const parsed = await parseImport(file);
      if (parsed.people.length === 0) {
        setStep({ kind: 'upload' });
        setError(parsed.warnings.join(' ') || 'No people found in that file.');
      } else {
        setStep({ kind: 'preview', parsed, selected: new Set(parsed.people.map((_, i) => i)) });
      }
    } catch (e) {
      setStep({ kind: 'upload' });
      setError(errorText(e, "Couldn't read that file."));
    }
  }

  async function confirm(parsed: ImportParsed, selected: Set<number>) {
    if (importing) return;
    setImporting(true);
    setError('');
    try {
      setStep({ kind: 'result', result: await confirmImport(parsed.people.filter((_, i) => selected.has(i))) });
    } catch (e) {
      setError(errorText(e, "Couldn't finish the import. Check People before importing again."));
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className={`${page} flex max-w-4xl flex-col gap-4`}>
      <div>
        <h1 className={pageTitle}>Import people</h1>
        <p className="m-0 mt-1 text-sm text-sf-ink-mute">From a CSV or vCard (.vcf) file. You review every row before anything is saved.</p>
      </div>
      {error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}

      {(step.kind === 'upload' || step.kind === 'parsing') && (
        <div className={`${card} flex flex-col gap-3 p-4`}>
          <label htmlFor="import-file" className="flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed border-sf-line-strong bg-sf-raised px-4 py-8 text-center text-sm text-sf-ink-mute">
            {file ? <span className="text-sf-ink">{file.name} ({(file.size / 1024).toFixed(1)} KB)</span> : 'Choose a file'}
            <input id="import-file" type="file" accept=".csv,.vcf,text/csv,text/vcard" className="sr-only"
              onChange={e => { setFile(e.target.files?.[0] ?? null); setError(''); }} />
          </label>
          <button type="button" onClick={() => void parse()} disabled={!file || step.kind === 'parsing'} className={`${btnPrimary} self-end`}>
            {step.kind === 'parsing' ? 'Reading…' : 'Preview'}
          </button>
        </div>
      )}

      {step.kind === 'preview' && (
        <Preview step={step} importing={importing}
          onToggle={selected => setStep({ ...step, selected })}
          onCancel={() => setStep({ kind: 'upload' })}
          onConfirm={() => void confirm(step.parsed, step.selected)} />
      )}

      {step.kind === 'result' && (
        <div className={`${card} flex flex-col gap-2 p-4 text-sm`}>
          <p className="m-0 font-medium text-sf-green-text">{step.result.created} {step.result.created === 1 ? 'person' : 'people'} imported</p>
          {step.result.organizations_linked > 0 && <p className="m-0 text-sf-ink-mute">{step.result.organizations_linked} linked to an organization.</p>}
          {step.result.skipped.length > 0 && (
            <>
              <p className="m-0 text-sf-ink-mute">{step.result.skipped.length} skipped:</p>
              <ul className="m-0 pl-5 text-sf-ink-soft">{step.result.skipped.slice(0, 20).map((s, i) => <li key={i}>{s}</li>)}</ul>
            </>
          )}
          <div className="mt-2 flex gap-2">
            <Link to="/people" className={btnSecondary}>Go to People</Link>
            <button type="button" onClick={() => { setFile(null); setStep({ kind: 'upload' }); }} className={btnSecondary}>Import another file</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Preview({ step, importing, onToggle, onCancel, onConfirm }: {
  step: { parsed: ImportParsed; selected: Set<number> };
  importing: boolean;
  onToggle: (selected: Set<number>) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { parsed, selected } = step;
  const all = selected.size === parsed.people.length;
  const toggle = (i: number) => {
    const next = new Set(selected);
    if (next.has(i)) next.delete(i); else next.add(i);
    onToggle(next);
  };
  return (
    <div className={`${card} flex flex-col gap-3 p-4`}>
      {parsed.method === 'ai' && <p className="m-0 text-sm text-sf-amber-text">Read with AI: check the rows before importing.</p>}
      {parsed.warnings.map((w, i) => <p key={i} className="m-0 text-sm text-sf-amber-text">{w}</p>)}
      <div className="flex items-center justify-between text-sm text-sf-ink-mute">
        <label className="flex cursor-pointer items-center gap-2">
          <input type="checkbox" checked={all} className="accent-sf-accent"
            onChange={() => onToggle(all ? new Set() : new Set(parsed.people.map((_, i) => i)))} />
          Select all ({parsed.people.length})
        </label>
        <span>{selected.size} selected</span>
      </div>
      <div className="max-h-96 overflow-auto rounded border border-sf-line">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-sf-raised text-left text-xs text-sf-ink-dim">
            <tr>
              <th className="w-8 px-2 py-2"><span className="sr-only">Import</span></th>
              <th className="px-2 py-2 font-medium">Name</th>
              <th className="px-2 py-2 font-medium">Email</th>
              <th className="px-2 py-2 font-medium">Phone</th>
              <th className="px-2 py-2 font-medium">Organization</th>
            </tr>
          </thead>
          <tbody>
            {parsed.people.map((p, i) => (
              <tr key={i} className={`border-t border-sf-line ${selected.has(i) ? 'text-sf-ink' : 'text-sf-ink-dim'}`}>
                <td className="px-2 py-2"><input type="checkbox" checked={selected.has(i)} onChange={() => toggle(i)} aria-label={`Import ${p.name}`} className="accent-sf-accent" /></td>
                <td className="px-2 py-2">{p.name}{p.title && <span className="text-sf-ink-dim"> ({p.title})</span>}</td>
                <td className="px-2 py-2">{p.email || '—'}</td>
                <td className="px-2 py-2">{p.phone || '—'}</td>
                <td className="px-2 py-2">{p.organization || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={btnSecondary}>Cancel</button>
        <button type="button" onClick={onConfirm} disabled={selected.size === 0 || importing} className={btnPrimary}>
          {importing ? 'Importing…' : `Import ${selected.size}`}
        </button>
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { ApiError, del, fetchJson, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { IconLock } from './icons';
import type { ContextFile, ContextFileMeta, Fact } from './types';
import { BUTTON, HINT, INPUT, LABEL, PRIMARY } from './ui';

const failure = (e: unknown, what: string) => (e instanceof ApiError ? `${what}: ${e.detail}` : `${what}.`);

/**
 * Whisk's context files, in prompt order (adapted from Chatty's AgentContextEditor). Admins
 * edit the unprotected ones here; soul.md and MEMORY.md are shown read-only, because they
 * change only through a chat request an admin approves.
 */
function ContextFiles() {
  const files = useJson<ContextFileMeta[]>('/api/core/context-files');
  const [file, setFile] = useState<ContextFile | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState('');
  const dirty = file !== null && draft !== file.content;

  async function open(name: string) {
    if (dirty && !(await confirmDialog({
      title: 'Discard changes', message: `Your edits to ${file?.filename} are not saved.`, confirmLabel: 'Discard', danger: true,
    }))) return;
    try {
      const f = await fetchJson<ContextFile>(`/api/core/context-files/${encodeURIComponent(name)}`);
      setFile(f);
      setDraft(f.content);
    } catch (e) {
      toast.error(failure(e, "Couldn't open the file"));
    }
  }

  async function save(name: string, content: string) {
    setBusy(true);
    try {
      const f = await putJson<ContextFile>(`/api/core/context-files/${encodeURIComponent(name)}`, { content });
      setFile(f);
      setDraft(f.content);
      files.reload();
      toast.success(`${f.filename} saved.`);
      return true;
    } catch (e) {
      toast.error(failure(e, "Couldn't save"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    const name = newName.trim().endsWith('.md') ? newName.trim() : `${newName.trim()}.md`;
    if (files.data?.some(f => f.filename.toLowerCase() === name.toLowerCase())) { void open(name); return; }
    if (dirty && !(await confirmDialog({ title: 'Discard changes', message: `Your edits to ${file?.filename} are not saved.`, confirmLabel: 'Discard', danger: true }))) return;
    if (await save(name, '')) setNewName('');
  }

  if (files.error) return <LoadError label="Couldn't load the context files" onRetry={files.reload} />;
  if (!files.data) return <BootFallback variant="panel" />;
  const meta = file && files.data.find(f => f.filename === file.filename);
  const readOnly = !meta?.can_edit;

  return (
    <div className="flex flex-col gap-3">
      <p className={HINT}>Context files are read into every conversation, in this order. Keep them short and factual.</p>
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Context files">
        {files.data.map(f => (
          <li key={f.filename}>
            <button type="button" onClick={() => void open(f.filename)} aria-pressed={file?.filename === f.filename}
              className={`flex cursor-pointer items-center gap-1.5 rounded-md border border-solid px-2.5 py-1 font-mono text-xs ${
                file?.filename === f.filename ? 'border-sf-accent bg-sf-accent-soft text-sf-ink' : 'border-sf-line-strong bg-transparent text-sf-ink-mute hover:text-sf-ink'}`}>
              {f.is_protected && <IconLock size={11} aria-hidden />}
              {f.filename}
              <span className="text-sf-ink-dim">{f.size_chars.toLocaleString()} ch</span>
            </button>
          </li>
        ))}
      </ul>
      <form className="flex items-end gap-2" onSubmit={e => { e.preventDefault(); if (newName.trim()) void create(); }}>
        <label className={`${LABEL} flex-1`}>
          New file
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="pricing.md" maxLength={100} className={INPUT} />
        </label>
        <button type="submit" disabled={busy || !newName.trim()} className={BUTTON}>Create</button>
      </form>

      {file && (
        <div className="flex flex-col gap-2">
          {file.is_protected && (
            <p className="m-0 flex items-start gap-1.5 rounded-md bg-sf-raised px-3 py-2 text-sm text-sf-ink-soft">
              <IconLock size={14} aria-hidden className="mt-0.5" />
              <span>
                {file.filename} shapes every answer, so it is read-only here. It changes only when an admin asks Whisk
                in chat and approves the change.
              </span>
            </p>
          )}
          <label className={LABEL}>
            {file.filename}{file.updated_at ? `, saved ${formatDate(file.updated_at)}` : ''}
            <textarea value={draft} onChange={e => setDraft(e.target.value)} readOnly={readOnly} rows={12} spellCheck={!readOnly}
              className={`${readOnly ? INPUT.replace('bg-sf-card', 'bg-sf-raised') : INPUT} resize-y font-mono text-[13px] leading-relaxed`} />
          </label>
          {!readOnly && (
            <div className="flex items-center gap-2">
              <button type="button" disabled={busy || !dirty} className={PRIMARY} onClick={() => void save(file.filename, draft)}>Save</button>
              {dirty && <button type="button" className={BUTTON} onClick={() => setDraft(file.content)}>Revert</button>}
              {dirty && <span className="text-xs text-sf-amber-text">Unsaved changes</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Business facts Whisk remembers, with where each came from; an admin can end one. */
function Facts() {
  const [input, setInput] = useState('');
  const [q, setQ] = useState('');
  const [ended, setEnded] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setQ(input.trim()), 250);
    return () => clearTimeout(id);
  }, [input]);
  const facts = useJson<Fact[]>(`/api/core/memory/facts?limit=100${q ? `&q=${encodeURIComponent(q)}` : ''}${ended ? '&history=true' : ''}`);

  async function end(f: Fact) {
    if (!(await confirmDialog({
      title: 'End this fact', message: `Whisk will stop using "${f.text}". The fact stays in the history.`, confirmLabel: 'End it', danger: true,
    }))) return;
    try {
      await del(`/api/core/memory/facts/${f.id}`);
      toast.success('Fact ended.');
      facts.reload();
    } catch (e) {
      toast.error(failure(e, "Couldn't end the fact"));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className={`${LABEL} min-w-48 flex-1`}>
          Search facts
          <input type="search" value={input} onChange={e => setInput(e.target.value)} className={INPUT} placeholder="delivery, hours, prices…" />
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 pb-2 text-xs text-sf-ink-mute">
          <input type="checkbox" checked={ended} onChange={e => setEnded(e.target.checked)} /> Show ended facts
        </label>
      </div>
      {facts.error && <LoadError compact label="Couldn't load the facts" onRetry={facts.reload} />}
      {!facts.error && !facts.data && <BootFallback variant="panel" />}
      {facts.data?.length === 0 && (
        <p className={HINT}>{q ? 'No fact matches.' : 'No facts yet. Whisk learns them from conversations overnight, when the nightly run is on.'}</p>
      )}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {facts.data?.map(f => (
          <li key={f.id} className={`flex flex-col gap-1 rounded-md border border-solid border-sf-line p-3 ${f.invalid_from ? 'opacity-70' : ''}`}>
            <div className="flex items-start justify-between gap-3">
              <span className={`text-sm text-sf-ink ${f.invalid_from ? 'line-through' : ''}`}>{f.text}</span>
              {!f.invalid_from && (
                <button type="button" className={`${BUTTON} shrink-0 px-2 py-1 text-xs`} onClick={() => void end(f)}>End validity</button>
              )}
            </div>
            {f.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {f.tags.map(t => <span key={t} className="rounded bg-sf-raised px-1.5 py-0.5 text-[11px] text-sf-ink-soft">{t}</span>)}
              </div>
            )}
            <p className="m-0 text-xs text-sf-ink-dim">
              {f.author_name ?? 'Unknown author'}
              {f.created_at ? `, ${formatDate(f.created_at)}` : ''}
              {', '}
              {f.source_conversation_id ? `from conversation #${f.source_conversation_id}` : 'added directly'}
              {f.invalid_from ? `. Ended ${formatDate(f.invalid_from)}` : `. Valid since ${formatDate(f.valid_from)}`}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Settings, AI: what Whisk knows. Conversations stay private to their owner; only ids show here. */
export default function MemoryCard() {
  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Context files" className="flex flex-col gap-2">
        <h3 className="m-0 text-sm font-medium text-sf-ink">Context files</h3>
        <ContextFiles />
      </section>
      <section aria-label="Facts" className="flex flex-col gap-2">
        <h3 className="m-0 text-sm font-medium text-sf-ink">Facts</h3>
        <Facts />
      </section>
    </div>
  );
}

/**
 * Files attached to a record: list, upload (multipart POST /api/core/files), download (a plain
 * link, the session cookie authorises it) and delete.
 */
import { useState, type ChangeEvent } from 'react';
import { del, upload } from '../api/client';
import type { FileRecord } from '../api/types';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';

export interface AttachmentsProps {
  entityType: string;
  entityId: number;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function Attachments({ entityType, entityId }: AttachmentsProps) {
  const query = new URLSearchParams({ entity_type: entityType, entity_id: String(entityId) });
  const { data: files, error, reload } = useJson<FileRecord[]>(`/api/core/files?${query}`);
  const [uploading, setUploading] = useState(false);

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const input = e.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('entity_type', entityType);
    form.append('entity_id', String(entityId));
    form.append('file', file);
    setUploading(true);
    try {
      await upload<FileRecord>('/api/core/files', form);
      reload();
    } catch {
      toast.error(`Couldn't upload ${file.name}.`);
    } finally {
      setUploading(false);
      input.value = '';
    }
  }

  async function remove(f: FileRecord) {
    const ok = await confirmDialog({ title: 'Delete file', message: `Delete ${f.filename}? This can't be undone.`, confirmLabel: 'Delete', danger: true });
    if (!ok) return;
    try {
      await del(`/api/core/files/${f.id}`);
      reload();
    } catch {
      toast.error(`Couldn't delete ${f.filename}.`);
    }
  }

  return (
    <section aria-label="Attachments" className="flex flex-col gap-3">
      <label className="w-fit cursor-pointer rounded-md border border-sf-line-strong px-3 py-1.5 text-sm text-sf-ink-mute hover:bg-sf-hover">
        {uploading ? 'Uploading…' : 'Upload a file'}
        <input type="file" className="sr-only" disabled={uploading} onChange={e => void onPick(e)} />
      </label>
      {error ? <LoadError label="Couldn't load the files" onRetry={reload} compact />
        : !files ? <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>
        : files.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">No files yet.</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line p-0">
            {files.map(f => (
              <li key={f.id} className="flex items-center gap-3 py-2 text-sm">
                <a href={`/api/core/files/${f.id}/download`} className="min-w-0 flex-1 truncate text-sf-accent-text">{f.filename}</a>
                <span className="hidden text-xs text-sf-ink-dim sm:inline">
                  {formatBytes(f.byte_size)} · {f.uploaded_by?.name ?? 'Unknown'} · {formatDate(f.created_at)}
                </span>
                <button type="button" onClick={() => void remove(f)}
                  className="cursor-pointer border-0 bg-transparent p-1 font-sans text-xs text-sf-red-text">
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}

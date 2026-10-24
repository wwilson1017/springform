import { useRef, useState } from 'react';
import { LoadError } from '../../shared/LoadError';
import { IconPlus } from '../../shared/icons';
import { formatDate } from '../../shared/formatDate';
import { IconLock, IconPencil, IconTrash } from './icons';
import type { Conversation } from './types';

interface Props {
  list: Conversation[] | null;
  failed: boolean;
  activeId: number | null;
  query: string;
  onQuery: (q: string) => void;
  onRetry: () => void;
  onNew: () => void;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => Promise<void>;
  onTogglePrivate: (c: Conversation) => void;
  onDelete: (c: Conversation) => void;
}

const ACTION = 'flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded border-0 bg-transparent p-0 text-sf-ink-dim hover:bg-sf-hover hover:text-sf-ink';

/**
 * The user's conversations (lifted in shape from Chatty's ConversationSidebar): search over
 * message text, new chat, rename in place, the private flag, delete. Row actions show on the
 * active row and on hover.
 */
export function ConversationSidebar({
  list, failed, activeId, query, onQuery, onRetry, onNew, onSelect, onRename, onTogglePrivate, onDelete,
}: Props) {
  const [editing, setEditing] = useState<{ id: number; title: string } | null>(null);
  // Enter and the blur that follows both commit; the first one wins.
  const committing = useRef(false);

  async function commit() {
    if (!editing || committing.current) return;
    const { id, title } = editing;
    if (!title.trim()) { setEditing(null); return; }
    committing.current = true;
    try {
      await onRename(id, title.trim());
      setEditing(null);
    } finally {
      committing.current = false;
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-col gap-2 p-3">
        <button type="button" onClick={onNew}
          className="flex cursor-pointer items-center justify-center gap-1.5 rounded-md border border-dashed border-sf-line-strong bg-transparent px-3 py-2 text-sm text-sf-ink-mute hover:text-sf-ink">
          <IconPlus size={15} aria-hidden /> New chat
        </button>
        <input type="search" value={query} onChange={e => onQuery(e.target.value)} placeholder="Search conversations"
          aria-label="Search conversations"
          className="w-full rounded-md border border-solid border-sf-line-strong bg-sf-card px-2.5 py-1.5 text-sm text-sf-ink placeholder:text-sf-ink-dim" />
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {failed && !list && <div className="px-1.5"><LoadError compact label="Couldn't load conversations" onRetry={onRetry} /></div>}
        {list && list.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-sf-ink-dim">{query.trim() ? 'No conversation mentions that.' : 'No conversations yet.'}</p>
        )}
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
          {list?.map(c => {
            const active = c.id === activeId;
            const isEditing = editing?.id === c.id;
            return (
              <li key={c.id}
                className={`group flex items-center gap-1 rounded-md pl-2.5 pr-1 ${active ? 'bg-sf-raised' : 'hover:bg-sf-hover'}`}>
                {isEditing ? (
                  <input autoFocus value={editing.title} aria-label="Conversation title" maxLength={200}
                    onChange={e => setEditing({ id: c.id, title: e.target.value })}
                    onBlur={() => void commit()}
                    onKeyDown={e => { if (e.key === 'Enter') void commit(); if (e.key === 'Escape') setEditing(null); }}
                    className="my-1 min-w-0 flex-1 rounded border border-solid border-sf-line-strong bg-sf-card px-2 py-1 text-sm text-sf-ink" />
                ) : (
                  <button type="button" onClick={() => onSelect(c.id)} aria-current={active ? 'page' : undefined}
                    className="flex min-w-0 flex-1 cursor-pointer flex-col items-start border-0 bg-transparent py-2 text-left">
                    <span className={`flex w-full items-center gap-1.5 text-sm ${active ? 'text-sf-ink' : 'text-sf-ink-mute'}`}>
                      {c.is_private && <IconLock size={12} aria-hidden className="text-sf-ink-dim" />}
                      <span className="truncate">{c.title || 'New conversation'}</span>
                    </span>
                    <span className="text-[11px] text-sf-ink-dim">{formatDate(c.updated_at)}</span>
                  </button>
                )}
                {!isEditing && (
                  <span className={`flex items-center ${active ? '' : 'md:hidden md:group-hover:flex md:group-focus-within:flex'}`}>
                    <button type="button" title="Rename" aria-label={`Rename ${c.title || 'conversation'}`} className={ACTION}
                      onClick={() => setEditing({ id: c.id, title: c.title })}>
                      <IconPencil size={14} aria-hidden />
                    </button>
                    <button type="button" aria-pressed={c.is_private}
                      title={c.is_private ? 'Private: Whisk does not learn from it. Click to allow.' : 'Make private: Whisk will not learn business facts from it.'}
                      aria-label={c.is_private ? 'Make not private' : 'Make private'}
                      className={`${ACTION} ${c.is_private ? 'text-sf-ink' : ''}`} onClick={() => onTogglePrivate(c)}>
                      <IconLock size={14} aria-hidden />
                    </button>
                    <button type="button" title="Delete" aria-label={`Delete ${c.title || 'conversation'}`} className={ACTION}
                      onClick={() => onDelete(c)}>
                      <IconTrash size={14} aria-hidden />
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}

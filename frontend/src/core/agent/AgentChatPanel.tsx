import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { toast } from '../../shared/toast';
import { IconX } from '../../shared/icons';
import { AgentMessageBubble, FileChip } from './AgentMessageBubble';
import type { ChatMessage } from './chatModel';
import type { DecideOptions, Decision } from './confirmState';
import { IconArrowUp, IconPaperclip, IconSparkle, IconStop } from './icons';
import { ATTACH_WHILE_RUNNING, type ContextUsage } from './useAgentChat';

/** What the server reads (backend/core/agent/uploads.py KINDS, MAX_FILES); it stays the judge. */
const EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'csv', 'xlsx', 'pdf', 'docx'];
const MAX_FILES = 5;
const isImage = (f: File) => /\.(jpe?g|png|webp)$/i.test(f.name);

const kTokens = (n: number) => (n >= 1000 ? `${Math.round(n / 100) / 10}k` : String(n));

function UsageFooter({ usage, agentName }: { usage: ContextUsage; agentName: string }) {
  const pct = Math.min(100, Math.round((usage.contextTokens / usage.contextWindow) * 100));
  return (
    <div
      className="flex items-center gap-2 text-[11px] text-sf-ink-dim"
      title={`How full the model's context is; ${agentName} summarizes older messages at 70%.`}
    >
      <span className="h-1 w-16 overflow-hidden rounded-full bg-sf-raised">
        <span
          className={`block h-full ${pct >= 70 ? 'bg-sf-amber' : 'bg-sf-ai'}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </span>
      <span className="tabular-nums">
        Context {kTokens(usage.contextTokens)} of {kTokens(usage.contextWindow)} tokens ({pct}%)
      </span>
    </div>
  );
}

interface Props {
  agentName: string;
  messages: ChatMessage[];
  streaming: boolean;
  usage: ContextUsage | null;
  notice: string | null;
  /** Above the messages: the conversation's title bar. */
  header?: ReactNode;
  /** Shown instead of the composer (and of the empty state), e.g. the zero-key card. */
  blocked?: ReactNode;
  onSend: (text: string, files?: File[]) => void;
  onStop: () => void;
  onDecide: (msgId: string, toolUseId: string, decision: Decision, opts?: DecideOptions) => Promise<void> | void;
}

/** The message list and the composer (Chatty's AgentChatPanel without modes or playbooks). */
export function AgentChatPanel({
  agentName,
  messages,
  streaming,
  usage,
  notice,
  header,
  blocked,
  onSend,
  onStop,
  onDecide,
}: Props) {
  const [draft, setDraft] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Follow the stream while the reader is at the bottom; leave them be once they scroll up.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (!streaming) inputRef.current?.focus();
  }, [streaming]);

  // The composer grows with its text up to about eight lines.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [draft]);

  function submit() {
    if (!(draft.trim() || files.length)) return; // while a reply runs, a message is queued for it
    if (streaming && files.length) return void toast.error(ATTACH_WHILE_RUNNING); // draft and files stay
    pinnedRef.current = true;
    onSend(draft, files);
    setDraft('');
    setFiles([]);
  }

  function pick(list: FileList | null) {
    const picked = [...(list ?? [])];
    const ok = picked.filter((f) => EXTENSIONS.includes(f.name.split('.').pop()?.toLowerCase() ?? ''));
    const bad = picked.find((f) => !ok.includes(f));
    if (bad) toast.error(`${bad.name} can't be attached. Attach photos (JPEG, PNG, WebP), PDF, Word, Excel or CSV.`);
    const next = [...files, ...ok];
    if (next.length > MAX_FILES) toast.error(`At most ${MAX_FILES} files per message.`);
    setFiles(next.slice(0, MAX_FILES));
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {header}
      <div
        ref={scrollRef}
        data-testid="chat-scroll"
        onScroll={(e) => {
          const el = e.currentTarget;
          pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6 md:px-6">
          {messages.length === 0 && blocked && <div className="py-10">{blocked}</div>}
          {messages.length === 0 && !blocked && (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-sf-ai/15 text-sf-ai-text">
                <IconSparkle size={24} aria-hidden />
              </span>
              <p className="m-0 font-display text-lg text-sf-ink">Ask {agentName}</p>
              <p className="m-0 max-w-sm text-sm text-sf-ink-soft">
                Questions about your records, or a change to make. {agentName} asks before it writes anything.
              </p>
            </div>
          )}
          {messages.map((m) => (
            <AgentMessageBubble key={m.id} message={m} agentName={agentName} busy={streaming} onDecide={onDecide} />
          ))}
          {notice && (
            <p role="status" className="m-0 text-center text-xs text-sf-amber-text">
              {notice}
            </p>
          )}
        </div>
      </div>
      {blocked && messages.length > 0 && (
        <div className="border-0 border-t border-solid border-sf-line px-4 py-4">{blocked}</div>
      )}
      {!blocked && (
        <div className="border-0 border-t border-solid border-sf-line bg-sf-bg px-4 pb-3 pt-3 md:px-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
            {files.length > 0 && (
              <ul aria-label="Attachments" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`}>
                    <FileChip filename={f.name} image={isImage(f)}>
                      <button
                        type="button"
                        onClick={() => setFiles(files.filter((_, j) => j !== i))}
                        aria-label={`Remove ${f.name}`}
                        className="-mr-1 flex cursor-pointer items-center border-0 bg-transparent p-0.5 text-sf-ink-dim"
                      >
                        <IconX size={12} aria-hidden />
                      </button>
                    </FileChip>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex items-end gap-2 rounded-lg border border-solid border-sf-line-strong bg-sf-card p-2 focus-within:border-sf-accent">
              <input
                ref={fileRef}
                type="file"
                multiple
                hidden
                accept={EXTENSIONS.map((e) => `.${e}`).join(',')}
                data-testid="chat-file-input"
                onChange={(e) => {
                  pick(e.target.files);
                  e.target.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                aria-label="Attach files"
                title="Attach photos or files"
                className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-sf-ink-mute"
              >
                <IconPaperclip size={18} aria-hidden />
              </button>
              <textarea
                ref={inputRef}
                value={draft}
                rows={1}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                aria-label={`Message ${agentName}`}
                placeholder={`Message ${agentName}…`}
                className="max-h-[200px] min-h-6 flex-1 resize-none border-0 bg-transparent px-1.5 py-1 text-[15px] leading-6 text-sf-ink outline-none placeholder:text-sf-ink-dim"
              />
              {streaming && (
                <button
                  type="button"
                  onClick={onStop}
                  aria-label="Stop"
                  className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border border-solid border-sf-line-strong bg-transparent text-sf-ink-mute"
                >
                  <IconStop size={16} aria-hidden />
                </button>
              )}
              {(!streaming || draft.trim()) && (
                <button
                  type="button"
                  onClick={submit}
                  aria-label="Send"
                  disabled={!draft.trim() && files.length === 0}
                  className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-sf-accent text-sf-accent-ink disabled:cursor-default disabled:opacity-40"
                >
                  <IconArrowUp size={16} aria-hidden />
                </button>
              )}
            </div>
            <div className="flex min-h-4 flex-wrap items-center justify-between gap-2 px-1 text-[11px] text-sf-ink-dim">
              <span className="hidden md:inline">Enter sends, Shift+Enter adds a line</span>
              {usage && <UsageFooter usage={usage} agentName={agentName} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

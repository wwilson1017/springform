import { memo, useState } from 'react';
import { MarkdownContent } from '../../shared/MarkdownContent';
import { IconChevronDown } from '../../shared/icons';
import { pretty, type ChatMessage, type ToolPart } from './chatModel';
import type { Decision } from './confirmState';
import { IconSparkle } from './icons';
import { ToolConfirmCard } from './ToolConfirmCard';

const DOT: Record<string, string> = {
  running: 'bg-sf-amber animate-pulse', pending: 'bg-sf-amber', executing: 'bg-sf-amber animate-pulse',
  done: 'bg-sf-green', error: 'bg-sf-red', denied: 'bg-sf-ink-dim', stale: 'bg-sf-amber',
  uncertain: 'bg-sf-amber', interrupted: 'bg-sf-amber',
};

const STATUS_LABEL: Record<string, string> = {
  running: 'running', pending: 'waiting for approval', executing: 'running', done: '', error: 'failed',
  denied: 'denied', stale: 'out of date', uncertain: 'outcome unknown', interrupted: 'interrupted',
};

/** One tool call, collapsed to a line; open it for the arguments and the result. */
function ToolCallBubble({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false);
  const elapsed = part.elapsedMs ? (part.elapsedMs < 1000 ? `${part.elapsedMs} ms` : `${(part.elapsedMs / 1000).toFixed(1)} s`) : '';
  return (
    <div className="overflow-hidden rounded-md border border-solid border-sf-line bg-sf-card text-xs">
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-2.5 py-1.5 text-left font-sans text-xs text-sf-ink-mute">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[part.status] ?? 'bg-sf-ink-dim'}`} />
        <code className="min-w-0 truncate font-mono text-sf-ink">{part.tool}</code>
        {STATUS_LABEL[part.status] && <span className="shrink-0 text-sf-ink-dim">{STATUS_LABEL[part.status]}</span>}
        <span className="ml-auto shrink-0 tabular-nums text-sf-ink-dim">{elapsed}</span>
        <IconChevronDown size={14} aria-hidden className={`shrink-0 text-sf-ink-dim transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="border-0 border-t border-solid border-sf-line px-2.5 pb-2.5 pt-1.5">
          {part.description && <p className="m-0 mb-1.5 italic text-sf-ink-dim">{part.description}</p>}
          <div className="text-[10px] font-semibold uppercase tracking-wider text-sf-ink-dim">Input</div>
          <pre className="mb-1.5 mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-sf-ink-mute">{pretty(part.args ?? {})}</pre>
          {(part.result !== undefined || part.error) && (
            <>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-sf-ink-dim">{part.error ? 'Error' : 'Output'}</div>
              <pre className={`m-0 mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono ${part.error ? 'text-sf-red-text' : 'text-sf-ink-mute'}`}>
                {part.error ?? pretty(part.result)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <div role="status" aria-label="Whisk is thinking" className="flex gap-1 py-2">
      {[0, 1, 2].map(i => (
        <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-sf-ai" style={{ animationDelay: `${i * 150}ms` }} />
      ))}
    </div>
  );
}

interface Props {
  message: ChatMessage;
  agentName: string;
  /** A turn is streaming: approval buttons wait for it to finish. */
  busy: boolean;
  onDecide: (msgId: string, toolUseId: string, decision: Decision) => void;
}

function Bubble({ message, agentName, busy, onDecide }: Props) {
  if (message.role === 'user') {
    const text = message.parts.map(p => (p.kind === 'text' ? p.text : '')).join('');
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-xl rounded-br-sm border border-solid border-sf-line bg-sf-raised px-4 py-2.5 text-[15px] leading-normal text-sf-ink">
          {text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <span aria-hidden className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sf-ai/15 text-sf-ai-text">
        <IconSparkle size={16} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="text-sm font-medium text-sf-ai-text">{agentName}</span>
          {message.model && <span className="font-mono text-[10px] text-sf-ink-dim">{message.model}</span>}
        </div>
        {message.compacted && (
          <p className="mb-2 mt-0 text-xs italic text-sf-ink-dim">Earlier messages were summarized to keep the conversation within the model's memory.</p>
        )}
        <div className="flex flex-col gap-2 text-[15px] text-sf-ink">
          {message.parts.map((part, i) => {
            if (part.kind === 'text') return <div key={i}><MarkdownContent content={part.text} /></div>;
            if (part.confirm) {
              return <ToolConfirmCard key={part.toolUseId} part={{ ...part, confirm: part.confirm }} disabled={busy}
                onDecide={d => onDecide(message.id, part.toolUseId, d)} />;
            }
            return <ToolCallBubble key={part.toolUseId} part={part} />;
          })}
        </div>
        {message.streaming && message.parts.length === 0 && <TypingDots />}
        {message.error && (
          <p role="alert" className="mb-0 mt-2 rounded border border-solid border-sf-red/30 bg-sf-red/8 px-3 py-2 text-sm text-sf-red-text">
            {message.error}
          </p>
        )}
      </div>
    </div>
  );
}

export const AgentMessageBubble = memo(Bubble);

import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useJson } from '../api/useJson';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import { confirmDialog } from '../../shared/confirm';
import { IconMenu, IconX } from '../../shared/icons';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { AgentChatPanel } from './AgentChatPanel';
import { ConversationSidebar } from './ConversationSidebar';
import { IconLock } from './icons';
import type { AgentRow, AgentStatus, Conversation } from './types';
import { useAgentChat } from './useAgentChat';
import { useConversations } from './useConversations';
import { ZeroKeyCard } from './ZeroKeyCard';

/**
 * `/whisk` and `/whisk/<conversation id>`: the conversation list beside the chat. The URL holds
 * the open conversation, so a thread can be linked and Back works; another user's id answers
 * 404 from the server and shows as not found. With no AI key the chat is replaced by the
 * zero-key card (the list and old threads still open).
 */
export default function WhiskPage() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const splat = useParams()['*'] ?? '';
  const urlId = /^\d+$/.test(splat) ? Number(splat) : null;

  const status = useJson<AgentStatus>('/api/agent/status');
  const agents = useJson<AgentRow[]>('/api/agent/agents');
  const conversations = useConversations();
  const { reload: reloadList, retitle } = conversations;
  const [drawer, setDrawer] = useState(false);
  const [openState, setOpenState] = useState<{ id: number; result: 'missing' | 'error' } | null>(null);

  // The conversation the stream created: already on screen when the URL catches up with it.
  const createdRef = useRef<number | null>(null);
  const chat = useAgentChat({
    onConversation: id => { createdRef.current = id; navigate(`/whisk/${id}`, { replace: true }); void reloadList(); },
    onTitle: retitle,
    onNoProvider: status.reload,
  });
  const { load, reset, currentId } = chat;

  // Follow the URL. (Not "skip when already open": StrictMode runs this twice, and the first
  // run's load has already adopted the id when the second one looks.)
  useEffect(() => {
    if (urlId == null) { if (currentId() != null) reset(); return; }
    if (urlId === createdRef.current && urlId === currentId()) return;
    let live = true;
    void load(urlId).then(result => { if (live) setOpenState(result === 'ok' ? null : { id: urlId, result }); });
    return () => { live = false; };
  }, [urlId, currentId, load, reset]);

  const agentName = useMemo(() => {
    const slug = status.data?.default_agent;
    return agents.data?.find(a => (slug ? a.slug === slug : a.is_default))?.name || 'Whisk';
  }, [agents.data, status.data]);
  const active = conversations.list?.find(c => c.id === chat.conversationId) ?? null;

  function newChat() {
    setDrawer(false);
    setOpenState(null);
    reset();
    navigate('/whisk');
  }

  async function rename(id: number, title: string) {
    try {
      await conversations.patch(id, { title });
    } catch {
      toast.error("Couldn't rename the conversation.");
    }
  }

  async function togglePrivate(c: Conversation) {
    try {
      const updated = await conversations.patch(c.id, { is_private: !c.is_private });
      toast.success(updated.is_private
        ? 'Private: Whisk will not learn business facts from this conversation.'
        : 'No longer private: Whisk may learn business facts from it overnight.');
    } catch {
      toast.error("Couldn't change the conversation.");
    }
  }

  async function remove(c: Conversation) {
    const ok = await confirmDialog({
      title: 'Delete conversation',
      message: `"${c.title || 'New conversation'}" and its messages will be deleted. This cannot be undone.`,
      confirmLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    try {
      await conversations.remove(c.id);
      if (currentId() === c.id) newChat();
    } catch {
      toast.error("Couldn't delete the conversation.");
    }
  }

  if (status.error) return <div className="mx-auto max-w-3xl px-4 py-8"><LoadError label="Couldn't reach Whisk" onRetry={status.reload} /></div>;
  if (!status.data) return <BootFallback variant="panel" />;

  const sidebar = (
    <ConversationSidebar
      list={conversations.list} failed={conversations.failed} activeId={chat.conversationId}
      query={conversations.query} onQuery={conversations.setQuery} onRetry={() => void reloadList()}
      onNew={newChat} onSelect={id => { setDrawer(false); navigate(`/whisk/${id}`); }}
      onRename={rename} onTogglePrivate={c => void togglePrivate(c)} onDelete={c => void remove(c)}
    />
  );

  const header = (
    <div className="flex h-11 shrink-0 items-center gap-2 border-0 border-b border-solid border-sf-line px-3 md:px-6">
      <button type="button" aria-label="Conversations" onClick={() => setDrawer(true)}
        className="flex cursor-pointer border-0 bg-transparent p-1 text-sf-ink-mute md:hidden">
        <IconMenu size={18} aria-hidden />
      </button>
      <h1 className="m-0 min-w-0 truncate font-display text-sm font-medium text-sf-ink">
        {active?.title || (chat.conversationId ? 'Conversation' : 'New chat')}
      </h1>
      {active?.is_private && (
        <span className="flex shrink-0 items-center gap-1 rounded-full bg-sf-raised px-2 py-0.5 text-[11px] text-sf-ink-soft"
          title="Whisk does not learn business facts from a private conversation.">
          <IconLock size={11} aria-hidden /> Private
        </span>
      )}
    </div>
  );

  const failedOpen = openState && openState.id === urlId ? openState : null;

  return (
    <div className="flex h-[calc(100svh-3.25rem)] min-h-0">
      <aside className="hidden w-64 shrink-0 border-0 border-r border-solid border-sf-line md:block">{sidebar}</aside>
      {drawer && (
        <div className="fixed inset-0 z-40 flex md:hidden" role="dialog" aria-modal="true" aria-label="Conversations">
          <div className="flex w-[85%] max-w-xs flex-col bg-sf-bg shadow-xl">
            <div className="flex items-center justify-between border-0 border-b border-solid border-sf-line px-3 py-2">
              <span className="font-display text-base text-sf-ink">Conversations</span>
              <button type="button" aria-label="Close conversations" onClick={() => setDrawer(false)}
                className="flex cursor-pointer border-0 bg-transparent p-1 text-sf-ink-mute"><IconX size={18} aria-hidden /></button>
            </div>
            <div className="min-h-0 flex-1">{sidebar}</div>
          </div>
          <button type="button" aria-label="Close conversations" onClick={() => setDrawer(false)} className="flex-1 border-0 bg-sf-scrim" />
        </div>
      )}
      {failedOpen ? (
        <div className="flex min-w-0 flex-1 flex-col">
          {header}
          <div className="mx-auto mt-16 max-w-md px-4 text-center">
            {failedOpen.result === 'missing' ? (
              <>
                <p className="m-0 font-display text-lg text-sf-ink">Conversation not found</p>
                <p className="mt-2 text-sm text-sf-ink-soft">It was deleted, or it belongs to someone else. Conversations are private to the person who started them.</p>
              </>
            ) : (
              <LoadError label="Couldn't load this conversation" onRetry={() => { setOpenState(null); void load(failedOpen.id).then(r => r !== 'ok' && setOpenState({ id: failedOpen.id, result: r })); }} />
            )}
            <button type="button" onClick={newChat}
              className="mt-4 cursor-pointer rounded-md border border-solid border-sf-line-strong bg-transparent px-4 py-2 text-sm text-sf-ink-mute">
              Start a new chat
            </button>
          </div>
        </div>
      ) : (
        <AgentChatPanel
          agentName={agentName} messages={chat.messages} streaming={chat.streaming} usage={chat.usage} notice={chat.notice}
          header={header} blocked={status.data.configured ? undefined : <ZeroKeyCard isAdmin={isAdmin} />}
          onSend={chat.send} onStop={chat.stop} onDecide={(m, t, d) => void chat.decide(m, t, d)}
        />
      )}
    </div>
  );
}

import { useLocation, useNavigate } from 'react-router';
import { IconSparkle } from './icons';
import type { ChatContext } from './types';
import { useAgentName } from './useAgentName';

/** The server's `ChatIn.page` pattern: a path it would refuse is left out rather than sent. */
const PLAIN_PATH = /^\/[A-Za-z0-9/_.~%-]*$/;

/** "Ask {assistant}" on a record page: opens the chat with this page and record attached (router
 *  state `agentContext`, read by WhiskPage). */
export function AskAgentButton({ entityType, entityId }: { entityType: string; entityId: number }) {
  const agentName = useAgentName();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const agentContext: ChatContext = {
    ...(PLAIN_PATH.test(pathname) && pathname.length <= 300 ? { page: pathname } : {}),
    record: { entity_type: entityType, entity_id: entityId },
  };
  return (
    <button
      type="button"
      onClick={() => navigate('/whisk', { state: { agentContext } })}
      className="inline-flex cursor-pointer items-center gap-1.5 self-start rounded-lg border border-solid border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-ink hover:bg-sf-hover"
    >
      <IconSparkle size={14} aria-hidden className="text-sf-ai-text" />
      Ask {agentName}
    </button>
  );
}

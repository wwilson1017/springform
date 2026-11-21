/**
 * Settings → Account → Saved approvals: the caller's always-allow rules (GET /api/agent/approval-rules).
 * Remove voids a rule (DELETE), and that tool asks again from its next call.
 */

import { useState } from 'react';
import { del } from '../api/client';
import { useJson } from '../api/useJson';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { btnSecondary, noteText } from '../auth/api';
import type { ApprovalRule } from './types';

export default function SavedApprovalsCard() {
  const rules = useJson<ApprovalRule[]>('/api/agent/approval-rules');
  const [busy, setBusy] = useState<number | null>(null);
  if (rules.error) return <LoadError label="Couldn't load your saved approvals" onRetry={rules.reload} compact />;
  if (!rules.data) return <p className={noteText}>Loading…</p>;
  if (rules.data.length === 0)
    return <p className={noteText}>No saved approvals. Tick Always allow on an Approve card to add one.</p>;

  async function remove(rule: ApprovalRule) {
    setBusy(rule.id);
    try {
      await del(`/api/agent/approval-rules/${rule.id}`);
      toast.success(`${rule.tool} will ask again.`);
      rules.reload();
    } catch {
      toast.error("Couldn't remove that approval.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <p className={noteText}>
        These tools run without an Approve card in your chats. They still ask in a conversation that has read outside
        content.
      </p>
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {rules.data.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
            <div className="min-w-0">
              <code className="break-all font-mono text-xs text-sf-ink">{r.tool}</code>
              <div className="text-xs text-sf-ink-dim">
                With {r.agent_name} · saved {formatDate(r.created_at)}
              </div>
            </div>
            <button type="button" disabled={busy === r.id} className={btnSecondary} onClick={() => void remove(r)}>
              Remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

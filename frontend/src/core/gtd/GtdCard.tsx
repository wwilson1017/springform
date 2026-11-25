import { useEffect, useRef, useState } from 'react';
import { ApiError, del, postJson, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import { useAgentName } from '../agent/useAgentName';
import BootFallback from '../components/BootFallback';
import { confirmDialog } from '../../shared/confirm';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { buttonClass, errorTextClass, inputClass, labelClass, secondaryButtonClass } from '../settings/ui';
import type { GtdState } from './types';

const BASE = '/api/core/gtd';
const SAYS: Record<string, string> = {
  gtd_connect_expired: 'That code expired or was already used. Connect again.',
  gtd_prefix_taken: 'Another MCP server already uses the prefix gtd. Remove it in Settings, MCP servers first.',
  prefix_taken: 'Another MCP server already uses the prefix gtd. Remove it in Settings, MCP servers, then check again.',
  gtd_already_connected: 'The GTD suite is already connected.',
};

/** The server writes sentences for the suite's own failures (502); its codes get one here. */
function say(e: unknown): string {
  if (!(e instanceof ApiError)) return "Couldn't reach this install. Try again.";
  return SAYS[e.detail] ?? (e.status === 500 ? 'Something went wrong. Try again.' : e.detail);
}

/**
 * Settings, GTD suite: connect a GTD suite account with a code (device flow), then show it connected.
 * While a code waits, the card asks the server every `interval` seconds; the server asks the suite.
 */
export default function GtdCard() {
  const agentName = useAgentName();
  const { data, error, reload, setData } = useJson<GtdState>(BASE);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  // Bumped with every button's answer, so a poll answer still in flight is dropped even before React runs
  // the effect cleanup below (that cleanup lands after the commit, leaving a gap a late answer slips through).
  const epoch = useRef(0);

  const pending = data?.pending ?? null;
  useEffect(() => {
    if (!pending) return;
    let cancelled = false; // a Cancel, Disconnect or newer answer ends this effect: its late answer is dropped
    const timer = setTimeout(
      () => {
        const asked = epoch.current;
        const stale = () => cancelled || asked !== epoch.current;
        postJson<GtdState>(`${BASE}/connect/poll`).then(
          (next) => {
            if (stale()) return;
            setProblem(null);
            setData(next);
          },
          (e: unknown) => {
            if (stale()) return;
            setProblem(say(e));
            reload(); // a fresh state re-arms the timer (a blip keeps the connect waiting) or ends it (expired)
          },
        );
      },
      Math.max(pending.interval, 1) * 1000,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [data, pending, reload, setData]);

  if (error) return <LoadError label="Couldn't load the GTD suite settings" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;

  async function act(fn: () => Promise<GtdState>) {
    setBusy(true);
    setProblem(null);
    try {
      const next = await fn();
      epoch.current += 1; // only on success: a failed action leaves the in-flight poll to re-arm the timer
      setData(next);
    } catch (e) {
      setProblem(say(e));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    const ok = await confirmDialog({
      title: 'Disconnect the GTD suite',
      message: `${agentName} loses the GTD tools, and the GTD tiles leave the launcher. The account itself is not touched.`,
      confirmLabel: 'Disconnect',
      danger: true,
    });
    if (ok) await act(() => del<GtdState>(BASE));
  }

  async function saveAddress(value: string) {
    setBusy(true);
    try {
      await putJson('/api/core/settings', { values: { 'mcp.gtd_base_url': value } });
      setAddress(null);
      reload();
    } catch (e) {
      toast.error(say(e));
    } finally {
      setBusy(false);
    }
  }

  const { server } = data;
  return (
    <div className="flex flex-col gap-4">
      {server ? (
        <>
          <p className="m-0 text-sm text-sf-ink-soft">
            Connected to <code className="text-xs">{data.base_url}</code>.{' '}
            {server.last_error ? (
              <span className="text-sf-red-text">{server.last_error}</span>
            ) : (
              `${server.tools.length} tools: ${agentName} reads without asking and asks before every change.`
            )}
          </p>
          <div>
            <button type="button" disabled={busy} className={secondaryButtonClass} onClick={() => void disconnect()}>
              Disconnect
            </button>
          </div>
        </>
      ) : pending ? (
        <>
          <p className="m-0 text-sm text-sf-ink-soft">
            Open the GTD suite, sign in or make an account, and approve this code:
          </p>
          <p className="m-0 font-mono text-2xl tracking-widest text-sf-ink" aria-label="Connect code">
            {pending.user_code}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <a href={pending.url} target="_blank" rel="noopener noreferrer" className={buttonClass + ' no-underline'}>
              Open the GTD suite ↗
            </a>
            <span className="text-sm text-sf-ink-mute">Waiting for approval…</span>
            <button
              type="button"
              disabled={busy}
              className={secondaryButtonClass}
              onClick={() => void act(() => postJson<GtdState>(`${BASE}/connect/poll`))}
            >
              Check again
            </button>
            <button
              type="button"
              disabled={busy}
              className={secondaryButtonClass}
              onClick={() => void act(() => del<GtdState>(BASE))}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="m-0 text-sm text-sf-ink-soft">
            Connect a GTD suite account (Todo, Notes, Projects, Sites and Brain). {agentName} then reads from it without
            asking and asks before every change, for every member: the connection belongs to the whole install. Tiles
            for each app appear on the launcher and open in a new tab.
          </p>
          <div>
            <button
              type="button"
              disabled={busy}
              className={buttonClass}
              onClick={() => void act(() => postJson<GtdState>(`${BASE}/connect`))}
            >
              Connect
            </button>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer text-sf-ink-mute">Use another GTD suite address</summary>
            <form
              className="mt-2 flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void saveAddress(address ?? data.base_url);
              }}
            >
              <label className="min-w-64 flex-1">
                <span className={labelClass}>Address</span>
                <input
                  className={inputClass}
                  value={address ?? data.base_url}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="https://todogtd.com"
                />
              </label>
              <button type="submit" disabled={busy} className={secondaryButtonClass}>
                Save
              </button>
            </form>
          </details>
        </>
      )}
      {problem && <p className={errorTextClass}>{problem}</p>}
    </div>
  );
}

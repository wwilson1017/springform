import { useEffect, useState, type ReactNode } from 'react';
import { ApiError, patchJson, postJson, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { CoreSettings } from '../settings/types';
import type { Skill, SkillsPage } from './types';
import { BUTTON, HINT, INPUT, LABEL, PRIMARY } from './ui';
import { useAgentName } from './useAgentName';

const KEY = 'agent.skills_review_enabled';
const PAGE = 50;
const failure = (e: unknown, what: string) => (e instanceof ApiError ? `${what}: ${e.detail}` : `${what}.`);
const SMALL = `${BUTTON} px-2 py-1 text-xs`;
const REVIEW_OUTCOME: Record<string, string> = {
  discarded: 'nothing kept, because a conversation it read was made private or changed meanwhile.',
  bad_reply: "nothing kept, because the model's answer was not in the expected form.",
  error: 'the model call failed; the next review reads the newest conversations.',
};

type Draft = { name: string; description: string; body: string };
const EMPTY: Draft = { name: '', description: '', body: '' };

/** Name, description and body; creates a skill, or saves an edit of `editing`. */
function SkillForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: Draft;
  submitLabel: string;
  onSubmit: (d: Draft) => Promise<boolean>;
  onCancel?: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value });
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        setBusy(true);
        void onSubmit(draft)
          .then((ok) => ok && !onCancel && setDraft(EMPTY))
          .finally(() => setBusy(false));
      }}
    >
      <div className="flex flex-wrap gap-2">
        <label className={`${LABEL} min-w-40 flex-1`}>
          Name
          <input
            value={draft.name}
            onChange={set('name')}
            placeholder="weekly-stock-count"
            maxLength={48}
            className={`${INPUT} font-mono`}
          />
        </label>
        <label className={`${LABEL} min-w-56 flex-[2]`}>
          Description
          <input
            value={draft.description}
            onChange={set('description')}
            placeholder="Count the stock and log it every Monday"
            maxLength={60}
            className={INPUT}
          />
        </label>
      </div>
      <label className={LABEL}>
        Steps
        <textarea
          value={draft.body}
          onChange={set('body')}
          rows={6}
          placeholder={'When to use it, then numbered steps.\n1. …'}
          className={`${INPUT} resize-y font-mono text-[13px] leading-relaxed`}
        />
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          className={PRIMARY}
          disabled={busy || !draft.name.trim() || !draft.description.trim() || !draft.body.trim()}
        >
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className={BUTTON} onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

/** One status's skills, PAGE at a time (Previous / Next, so no list is ever cut short). */
function useSkills(status: Skill['status']) {
  const [offset, setOffset] = useState(0);
  const page = useJson<SkillsPage>(`/api/core/skills?status=${status}&limit=${PAGE}&offset=${offset}`);
  return { ...page, offset, setOffset };
}

function SkillRow({
  skill,
  onChanged,
  children,
}: {
  skill: Skill;
  onChanged: () => void;
  children?: (edit: () => void) => ReactNode;
}) {
  const agentName = useAgentName();
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(skill.status === 'proposed');

  async function save(d: Draft) {
    try {
      await patchJson(`/api/core/skills/${skill.id}`, d);
      toast.success(`${d.name} saved.`);
      setEditing(false);
      onChanged();
      return true;
    } catch (e) {
      toast.error(failure(e, "Couldn't save the skill"));
      return false;
    }
  }

  const by = skill.author === 'agent' ? `Proposed by ${agentName}` : `Written by ${skill.author_name ?? 'an admin'}`;
  return (
    <li className="flex flex-col gap-2 rounded-md border border-solid border-sf-line p-3">
      {editing ? (
        <SkillForm
          initial={{ name: skill.name, description: skill.description, body: skill.body }}
          submitLabel="Save"
          onSubmit={save}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="font-mono text-sm text-sf-ink">{skill.name}</span>
              <span className="text-sm text-sf-ink-soft">{skill.description}</span>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5">{children?.(() => setEditing(true))}</div>
          </div>
          <p className="m-0 text-xs text-sf-ink-dim">
            {by}
            {skill.source_conversation_id ? ` from conversation #${skill.source_conversation_id}` : ''}
            {`, ${formatDate(skill.created_at)}`}
            {skill.revises_name ? `. Replaces ${skill.revises_name}` : ''}
            {skill.status !== 'proposed' &&
              `. Used ${skill.use_count} ${skill.use_count === 1 ? 'time' : 'times'}${
                skill.last_used_at ? `, last ${formatDate(skill.last_used_at)}` : ''
              }`}
          </p>
          <button
            type="button"
            className="cursor-pointer self-start border-0 bg-transparent p-0 text-xs text-sf-ink-mute underline hover:text-sf-ink"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
          >
            {open ? 'Hide steps' : 'Show steps'}
          </button>
          {open && (
            <pre className="m-0 rounded-md bg-sf-raised px-3 py-2 font-mono text-[13px] leading-relaxed whitespace-pre-wrap text-sf-ink">
              {skill.body}
            </pre>
          )}
        </>
      )}
    </li>
  );
}

function Section({
  title,
  status,
  empty,
  actions,
  reloadKey,
  onChanged,
}: {
  title: string;
  status: Skill['status'];
  empty: string;
  actions: (s: Skill, edit: () => void, changed: () => void) => ReactNode;
  reloadKey: number;
  onChanged: () => void;
}) {
  const page = useSkills(status);
  const { reload, offset, setOffset } = page;
  const total = page.data?.total;
  useEffect(() => {
    if (reloadKey) reload(); // a change in any section can move a skill into this one
  }, [reloadKey, reload]);
  useEffect(() => {
    // a page emptied by an action moves back to the last page that has rows
    if (total !== undefined && offset > 0 && offset >= total)
      setOffset(Math.max(0, Math.ceil(total / PAGE) - 1) * PAGE);
  }, [total, offset, setOffset]);
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h3 className="m-0 text-sm font-medium text-sf-ink">
        {title}
        {page.data && page.data.total > 0 ? ` (${page.data.total})` : ''}
      </h3>
      {page.error && (
        <LoadError compact label={`Couldn't load the ${title.toLowerCase()} skills`} onRetry={page.reload} />
      )}
      {!page.error && !page.data && <BootFallback variant="panel" />}
      {page.data?.skills.length === 0 && <p className={HINT}>{empty}</p>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {page.data?.skills.map((s) => (
          <SkillRow key={`${s.id}-${s.updated_at}`} skill={s} onChanged={onChanged}>
            {(edit) => actions(s, edit, onChanged)}
          </SkillRow>
        ))}
      </ul>
      {page.data && (page.data.total > PAGE || page.offset > 0) && (
        <div className="flex items-center gap-2 text-xs text-sf-ink-dim">
          <button
            type="button"
            className={SMALL}
            disabled={page.offset === 0}
            onClick={() => page.setOffset(Math.max(0, page.offset - PAGE))}
          >
            Previous
          </button>
          <button
            type="button"
            className={SMALL}
            disabled={page.offset + PAGE >= page.data.total}
            onClick={() => page.setOffset(page.offset + PAGE)}
          >
            Next
          </button>
          {page.offset + 1}-{Math.min(page.offset + PAGE, page.data.total)} of {page.data.total}
        </div>
      )}
    </section>
  );
}

function ReviewSwitch() {
  const agentName = useAgentName();
  const { data, error, reload, setData } = useJson<CoreSettings>('/api/core/settings');
  const last = useJson<SkillsPage>('/api/core/skills?status=proposed&limit=1');
  const [busy, setBusy] = useState(false);
  if (error) return <LoadError label="Couldn't load the setting" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  const on = data.values[KEY] === true;

  async function toggle(next: boolean) {
    setBusy(true);
    try {
      setData(await putJson<CoreSettings>('/api/core/settings', { values: { [KEY]: next } }));
      toast.success(next ? 'Skills review on.' : 'Skills review off.');
    } catch {
      toast.error("Couldn't save the setting.");
    } finally {
      setBusy(false);
    }
  }

  const review = last.data?.last_review;
  return (
    <div className="flex flex-col gap-2">
      <label className="flex cursor-pointer items-center gap-2 text-sm text-sf-ink">
        <input type="checkbox" checked={on} disabled={busy} onChange={(e) => void toggle(e.target.checked)} />
        Propose skills from conversations
      </label>
      <p className={HINT}>
        After every ten finished turns, {agentName} reads the recent conversations that are not private and proposes a
        skill when one shows a method worth keeping. Nothing is used until an admin approves it here. It uses the main
        model, so it costs a little, and it is skipped while no AI key is set.
      </p>
      {review && (
        <p className="m-0 text-xs text-sf-ink-dim">
          Last review {formatDate(review.ran_at)}:{' '}
          {review.status === 'ok' || review.status === 'nothing_to_read'
            ? `${review.proposals} proposed.`
            : (REVIEW_OUTCOME[review.status] ?? 'nothing proposed.')}
        </p>
      )}
    </div>
  );
}

/** Settings, AI: the skills the assistant can load, the proposals waiting for review, and the switch. */
export default function SkillsCard() {
  const agentName = useAgentName();
  const [version, setVersion] = useState(0);
  const changed = () => setVersion((v) => v + 1);

  async function move(s: Skill, action: 'approve' | 'reject' | 'archive' | 'restore', done: string) {
    try {
      await postJson(`/api/core/skills/${s.id}/${action}`);
      toast.success(done);
      changed();
    } catch (e) {
      toast.error(failure(e, `Couldn't ${action} ${s.name}`));
    }
  }

  async function reject(s: Skill) {
    if (
      await confirmDialog({
        title: 'Reject this skill',
        message: `${agentName} will not use "${s.name}" and will not propose it again.`,
        confirmLabel: 'Reject',
        danger: true,
      })
    )
      await move(s, 'reject', `${s.name} rejected.`);
  }

  async function pin(s: Skill, pinned: boolean) {
    try {
      await patchJson(`/api/core/skills/${s.id}`, { pinned });
      changed();
    } catch (e) {
      toast.error(failure(e, "Couldn't save the pin"));
    }
  }

  async function create(d: Draft) {
    try {
      await postJson('/api/core/skills', d);
      toast.success(`${d.name} added.`);
      changed();
      return true;
    } catch (e) {
      toast.error(failure(e, "Couldn't add the skill"));
      return false;
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <p className={HINT}>
        A skill is a short, named method. {agentName} sees each active skill&apos;s name and description in every
        conversation and loads its steps when a task calls for one. Skills unused for 60 days are archived unless
        pinned.
      </p>
      <ReviewSwitch />
      <Section
        title="Proposed"
        status="proposed"
        empty="Nothing waiting for review."
        reloadKey={version}
        onChanged={changed}
        actions={(s, edit) => (
          <>
            <button
              type="button"
              className={`${PRIMARY} px-2 py-1 text-xs`}
              onClick={() => void move(s, 'approve', `${s.name} approved.`)}
            >
              Approve
            </button>
            <button type="button" className={SMALL} onClick={edit}>
              Edit
            </button>
            <button type="button" className={SMALL} onClick={() => void reject(s)}>
              Reject
            </button>
          </>
        )}
      />
      <Section
        title="Active"
        status="active"
        empty="No skills yet. Write one below, or turn on the review to have some proposed."
        reloadKey={version}
        onChanged={changed}
        actions={(s, edit) => (
          <>
            <label className="flex cursor-pointer items-center gap-1 text-xs text-sf-ink-mute">
              <input type="checkbox" checked={s.pinned} onChange={(e) => void pin(s, e.target.checked)} /> Pin
            </label>
            <button type="button" className={SMALL} onClick={edit}>
              Edit
            </button>
            <button type="button" className={SMALL} onClick={() => void move(s, 'archive', `${s.name} archived.`)}>
              Archive
            </button>
          </>
        )}
      />
      <Section
        title="Archived"
        status="archived"
        empty="Nothing archived."
        reloadKey={version}
        onChanged={changed}
        actions={(s) => (
          <button type="button" className={SMALL} onClick={() => void move(s, 'restore', `${s.name} restored.`)}>
            Restore
          </button>
        )}
      />
      <section aria-label="New skill" className="flex flex-col gap-2">
        <h3 className="m-0 text-sm font-medium text-sf-ink">New skill</h3>
        <SkillForm initial={EMPTY} submitLabel="Add skill" onSubmit={create} />
      </section>
    </div>
  );
}

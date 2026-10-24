import { useState } from 'react';
import { updateProject } from '../api';
import { toast } from '../toast';
import type { TodoProject } from '../types';
import { withOwnArea } from '../util';

import type { ProjectFieldValues } from '../constants';

type Area = { id: number; name: string };

const fieldCls =
  'min-w-0 rounded-lg border border-sf-line-strong bg-sf-card px-2 py-1.5 text-sm text-sf-ink placeholder:text-sf-ink-dim focus:border-sf-accent focus:outline-none disabled:opacity-50';

/** Area, purpose and outcome as plain controlled inputs. `onCommit` fires when a
 *  value is settled: on blur for the text fields, at once for the area. */
export function ProjectFields({ values, areas, disabled, onChange, onCommit }: {
  values: ProjectFieldValues;
  areas: Area[];
  disabled?: boolean;
  onChange: (next: ProjectFieldValues) => void;
  onCommit?: (next: ProjectFieldValues) => void;
}) {
  return (
    <div className="grid w-full gap-2 sm:grid-cols-2" data-project-fields>
      <select
        aria-label="Project area"
        value={values.area_id ?? ''}
        disabled={disabled}
        onChange={e => {
          const next = { ...values, area_id: e.target.value ? Number(e.target.value) : null };
          onChange(next);
          onCommit?.(next);
        }}
        className={`${fieldCls} sm:col-span-2`}
      >
        <option value="">No area</option>
        {areas.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
      {(['purpose', 'outcome'] as const).map(f => (
        <input
          key={f}
          aria-label={f === 'purpose' ? 'Project purpose' : 'Project outcome'}
          placeholder={f === 'purpose' ? 'Purpose — why does this matter?' : 'Outcome — what does done look like?'}
          value={values[f]}
          disabled={disabled}
          onChange={e => onChange({ ...values, [f]: e.target.value })}
          onBlur={() => onCommit?.(values)}
          className={fieldCls}
        />
      ))}
    </div>
  );
}

const valuesOf = (p: TodoProject): ProjectFieldValues => ({
  area_id: p.area_id ?? null, purpose: p.purpose ?? '', outcome: p.outcome ?? '',
});

/** The same fields bound to an EXISTING project: each settled change is written to
 *  the project itself. `onSaved` lets the caller refresh its cached project list. */
export function ProjectDetails({ project, areas, disabled, onSaved }: {
  project: TodoProject;
  areas: Area[];
  disabled?: boolean;
  onSaved: () => void;
}) {
  const saved = valuesOf(project);
  const [draft, setDraft] = useState(saved);
  // Re-seed, during render, only the fields whose SAVED value moved (our own write
  // echoing back, or an edit made elsewhere) — never a field still being typed in,
  // which is one whose draft no longer matches what it was last seeded with.
  const [seeded, setSeeded] = useState(saved);
  const moved = (Object.keys(saved) as (keyof ProjectFieldValues)[]).filter(k => saved[k] !== seeded[k]);
  if (moved.length > 0) {
    setSeeded(saved);
    setDraft(d => ({
      ...d, ...Object.fromEntries(moved.filter(k => d[k] === seeded[k]).map(k => [k, saved[k]])),
    }));
  }

  const commit = (next: ProjectFieldValues) => {
    const changed = Object.fromEntries(
      (Object.keys(next) as (keyof ProjectFieldValues)[])
        .filter(k => next[k] !== saved[k]).map(k => [k, next[k]]),
    );
    if (Object.keys(changed).length === 0) return;
    updateProject(project.id, changed).then(onSaved).catch(e => {
      toast.error(e instanceof Error ? e.message : 'Could not save the project.');
    });
  };

  const options = withOwnArea(areas, project.area_id, project.area_name);

  return <ProjectFields values={draft} areas={options} disabled={disabled} onChange={setDraft} onCommit={commit} />;
}

import { useId } from 'react';
import { isRequired, paramEntries, type ParamValues } from './reportParams';
import type { ReportParam, ReportParamsSchema } from './types';
import { INPUT, LABEL } from './ui';

/**
 * One input per param of a report's schema (`backend/core/reports/registry.py`): an enum is a
 * select, a date-format string a date input, integer and number a number input, boolean a
 * yes/no select. Optional params get an empty choice so "not set" stays expressible.
 */
export function ReportParamsForm({ schema, values, onChange }: {
  schema: ReportParamsSchema | null;
  values: ParamValues;
  onChange: (values: ParamValues) => void;
}) {
  const prefix = useId();
  const params = paramEntries(schema);
  if (params.length === 0) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {params.map(([name, p]) => {
        const id = `${prefix}-${name}`;
        const required = isRequired(schema, name);
        return (
          <div key={name}>
            <label htmlFor={id} className={LABEL}>{p.title ?? name}{required ? ' *' : ''}</label>
            <ParamInput id={id} param={p} required={required} value={values[name] ?? ''}
              onChange={v => onChange({ ...values, [name]: v })} />
            {p.description && <p className="m-0 mt-1 text-xs text-sf-ink-dim">{p.description}</p>}
          </div>
        );
      })}
    </div>
  );
}

function ParamInput({ id, param, required, value, onChange }: {
  id: string;
  param: ReportParam;
  required: boolean;
  value: string;
  onChange: (v: string) => void;
}) {
  const common = { id, required, value, className: INPUT };
  const choices = param.enum ?? (param.type === 'boolean' ? [true, false] : null);
  if (choices) {
    return (
      <select {...common} onChange={e => onChange(e.target.value)}>
        {(!required || value === '') && <option value="">—</option>}
        {choices.map(c => <option key={String(c)} value={String(c)}>{typeof c === 'boolean' ? (c ? 'Yes' : 'No') : String(c)}</option>)}
      </select>
    );
  }
  if (param.type === 'integer' || param.type === 'number') {
    return <input {...common} type="number" step={param.type === 'integer' ? 1 : 'any'} onChange={e => onChange(e.target.value)} />;
  }
  return <input {...common} type={param.format === 'date' ? 'date' : 'text'} onChange={e => onChange(e.target.value)} />;
}

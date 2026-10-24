import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { ReportParamsForm } from './ReportParamsForm';
import { initialParams, missingParams, paramsQuery, type ParamValues } from './reportParams';
import type { ReportParamsSchema } from './types';

const schema: ReportParamsSchema = {
  type: 'object',
  properties: {
    since: { type: 'string', format: 'date', title: 'Since' },
    stage: { type: 'string', enum: ['lead', 'won'], default: 'lead', title: 'Stage' },
    min_cents: { type: 'integer', title: 'Minimum', description: 'In cents' },
    ratio: { type: 'number' },
    archived: { type: 'boolean', title: 'Include archived' },
    q: { type: 'string' },
  },
  required: ['since'],
};

function Host({ onValues }: { onValues: (v: ParamValues) => void }) {
  const [values, setValues] = useState(() => initialParams(schema));
  return <ReportParamsForm schema={schema} values={values} onChange={v => { setValues(v); onValues(v); }} />;
}

describe('report params', () => {
  it('start from the defaults and build a query of the set values only', () => {
    const values = initialParams(schema);
    expect(values).toEqual({ since: '', stage: 'lead', min_cents: '', ratio: '', archived: '', q: '' });
    expect(missingParams(schema, values)).toEqual(['Since']);
    expect(paramsQuery({ ...values, since: '2026-01-01', q: 'a&b' })).toBe('since=2026-01-01&stage=lead&q=a%26b');
    expect(initialParams(null)).toEqual({});
  });
});

describe('ReportParamsForm', () => {
  it('renders one input per param, by type, and marks the required one', () => {
    let latest: ParamValues = {};
    render(<Host onValues={v => { latest = v; }} />);
    expect((screen.getByLabelText('Since *') as HTMLInputElement).type).toBe('date');
    expect((screen.getByLabelText('Minimum') as HTMLInputElement).step).toBe('1');
    expect((screen.getByLabelText('ratio') as HTMLInputElement).step).toBe('any');
    expect((screen.getByLabelText('q') as HTMLInputElement).type).toBe('text');
    expect(screen.getByText('In cents')).toBeTruthy();

    const stage = screen.getByLabelText('Stage') as HTMLSelectElement;
    expect(stage.value).toBe('lead');
    expect([...stage.options].map(o => o.value)).toEqual(['', 'lead', 'won']);
    const archived = screen.getByLabelText('Include archived') as HTMLSelectElement;
    expect([...archived.options].map(o => o.textContent)).toEqual(['—', 'Yes', 'No']);

    fireEvent.change(archived, { target: { value: 'true' } });
    fireEvent.change(screen.getByLabelText('Since *'), { target: { value: '2026-10-01' } });
    expect(latest).toMatchObject({ archived: 'true', since: '2026-10-01', stage: 'lead' });
    expect(missingParams(schema, latest)).toEqual([]);
  });

  it('renders nothing for a report without params', () => {
    const { container } = render(<ReportParamsForm schema={null} values={{}} onChange={() => {}} />);
    expect(container.innerHTML).toBe('');
  });
});

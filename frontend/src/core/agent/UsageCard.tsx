import { useState } from 'react';
import { del, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { CoreSettings } from '../settings/types';
import type { UsageMonth } from './types';
import { BUTTON, HINT, INPUT, PRIMARY } from './ui';

const KEY = 'agent.cost_rates';
const SETTINGS = '/api/core/settings';
const FIELDS = [
  ['input', 'Input'],
  ['output', 'Output'],
  ['cache_read', 'Cache read'],
  ['cache_write', 'Cache write'],
] as const;
type Field = (typeof FIELDS)[number][0];
type Rates = Record<string, Record<Field, number>>;
type Draft = Record<string, Record<Field, string>>;

function dollars(micros: number): string {
  const usd = micros / 1e6;
  const digits = usd > 0 && usd < 1 ? 4 : 2;
  return usd.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const count = (n: number) => n.toLocaleString('en-US');

function toDraft(rates: Rates, unpriced: string[]): Draft {
  const draft: Draft = {};
  for (const [model, rate] of Object.entries(rates)) {
    draft[model] = Object.fromEntries(FIELDS.map(([f]) => [f, String(rate[f] ?? 0)])) as Record<Field, string>;
  }
  for (const model of unpriced) draft[model] ??= { input: '', output: '', cache_read: '', cache_write: '' };
  return draft;
}

/** A model the admin never priced stays unpriced until one of its rates is typed in. */
function fromDraft(draft: Draft, priced: Set<string>): Rates {
  const out: Rates = {};
  for (const [model, rate] of Object.entries(draft)) {
    if (!priced.has(model) && FIELDS.every(([f]) => rate[f].trim() === '')) continue;
    out[model] = Object.fromEntries(FIELDS.map(([f]) => [f, Number(rate[f]) || 0])) as Record<Field, number>;
  }
  return out;
}

/** Settings, AI: this month's model usage and estimated cost, and the rates it is priced at. */
export default function UsageCard() {
  const month = useJson<UsageMonth>('/api/agent/usage');
  const settings = useJson<CoreSettings>(SETTINGS);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  if (month.error || settings.error)
    return (
      <LoadError
        label="Couldn't load usage"
        onRetry={() => {
          month.reload();
          settings.reload();
        }}
      />
    );
  if (!month.data || !settings.data) return <BootFallback variant="panel" />;

  const rates = (settings.data.values[KEY] ?? {}) as Rates;
  const priced = new Set(Object.keys(rates));
  const unpricedModels = [...new Set(month.data.rows.filter((r) => !priced.has(r.model)).map((r) => r.model))];
  const rows = draft ?? toDraft(rates, unpricedModels);
  const unpriced = month.data.rows.reduce((n, r) => n + r.unpriced, 0);
  const hit = month.data.cache_hit_rate;

  async function save() {
    setBusy(true);
    try {
      settings.setData(await putJson<CoreSettings>(SETTINGS, { values: { [KEY]: fromDraft(rows, priced) } }));
      setDraft(null);
      toast.success('Rates saved. They apply to calls from now on.');
    } catch {
      toast.error("Couldn't save the rates. Each must be a number from 0 to 10,000.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await del(`${SETTINGS}/${KEY}`);
      setDraft(null);
      settings.reload();
      toast.success('Rates reset to list prices.');
    } catch {
      toast.error("Couldn't reset the rates.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="text-2xl font-semibold text-sf-ink" data-testid="usage-total">
          {dollars(month.data.cost_micros)}
        </div>
        <p className={HINT}>
          Estimated spend for {month.data.month}
          {hit !== null && <>, {Math.round(hit * 100)}% of input read from the cache</>}. Estimated from the rates
          below; your provider's invoice is the real figure.
        </p>
      </div>
      {month.data.rows.length === 0 ? (
        <p className={HINT}>No AI calls yet this month.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm text-sf-ink">
            <thead>
              <tr className="text-left text-xs text-sf-ink-dim">
                <th className="py-1 pr-3 font-normal">Source</th>
                <th className="py-1 pr-3 font-normal">Model</th>
                <th className="py-1 pr-3 text-right font-normal">Calls</th>
                <th className="py-1 pr-3 text-right font-normal">Input</th>
                <th className="py-1 pr-3 text-right font-normal">Output</th>
                <th className="py-1 text-right font-normal">Cost</th>
              </tr>
            </thead>
            <tbody>
              {month.data.rows.map((r) => (
                <tr key={`${r.source} ${r.model}`} className="border-t border-solid border-sf-line">
                  <td className="py-1 pr-3">{r.source}</td>
                  <td className="py-1 pr-3 break-all">{r.model}</td>
                  <td className="py-1 pr-3 text-right">{count(r.calls)}</td>
                  <td className="py-1 pr-3 text-right">{count(r.input_tokens + r.cache_read + r.cache_write)}</td>
                  <td className="py-1 pr-3 text-right">{count(r.output_tokens)}</td>
                  <td className="py-1 text-right">{r.unpriced === r.calls ? 'no rate' : dollars(r.cost_micros)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {unpriced > 0 && (
        <p className={HINT}>
          {count(unpriced)} {unpriced === 1 ? 'call' : 'calls'} ran on a model with no rate and{' '}
          {unpriced === 1 ? 'is' : 'are'} not in the total.
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-sm text-sf-ink-mute">Rates (USD per million tokens)</summary>
        <div className="mt-2 flex flex-col gap-3">
          {Object.entries(rows).map(([model, rate]) => (
            <fieldset key={model} className="m-0 flex flex-col gap-1 border-0 p-0">
              <legend className="mb-1 p-0 text-sm text-sf-ink break-all">{model}</legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {FIELDS.map(([f, label]) => (
                  <label key={f} className="flex min-w-0 flex-col gap-1 text-xs text-sf-ink-dim">
                    {label}
                    <input
                      className={INPUT}
                      inputMode="decimal"
                      aria-label={`${model} ${label}`}
                      value={rate[f]}
                      onChange={(e) => setDraft({ ...rows, [model]: { ...rate, [f]: e.target.value } })}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <div className="flex flex-wrap gap-2">
            <button type="button" className={PRIMARY} disabled={busy || draft === null} onClick={() => void save()}>
              Save rates
            </button>
            <button type="button" className={BUTTON} disabled={busy} onClick={() => void reset()}>
              Reset to list prices
            </button>
          </div>
          <p className={HINT}>
            The defaults are list prices and may be out of date. A change prices calls from now on; past calls keep the
            cost they were recorded with.
          </p>
        </div>
      </details>
    </div>
  );
}

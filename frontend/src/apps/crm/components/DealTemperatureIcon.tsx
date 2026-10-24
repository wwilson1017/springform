/**
 * The deal temperature glyph, and with `onCycle` the one-click control that steps
 * `not set → hot → warm → cold → not set`. Hot is a flame, warm a filled dot, cold a ring,
 * untriaged a dashed ring (null is not cold, so it never looks like cold). While the write is
 * in flight the next tier shows; the caller reports a failure.
 */
import { useRef, useState, type MouseEvent } from 'react';
import { type DealTemperature, nextTemperature, normalizeTemperature, temperatureLabel } from '../dealTemperature';

function Glyph({ tier }: { tier: DealTemperature | null }) {
  if (tier === 'hot') {
    return (
      <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" className="text-sf-red-text">
        <path d="M12 21a6 6 0 0 0 6-6c0-4-3-6-4-9-1 2-2 3-3 3 0-2-1-4-2-5-1 3-3 6-3 11a6 6 0 0 0 6 6z" />
      </svg>
    );
  }
  const cls = tier === 'warm' ? 'bg-sf-amber'
    : tier === 'cold' ? 'border-[1.5px] border-solid border-sf-ink-dim'
    : 'border border-dashed border-sf-line-strong';
  return <span aria-hidden data-temperature={tier ?? 'none'} className={`box-border inline-block h-2 w-2 rounded-full ${cls}`} />;
}

export function DealTemperatureIcon({ value, onCycle, disabled = false }: {
  value: string | null | undefined;
  onCycle?: (next: DealTemperature | null) => Promise<unknown>;
  disabled?: boolean;
}) {
  const [pending, setPending] = useState<{ tier: DealTemperature | null } | null>(null);
  const op = useRef(0);
  const shown = pending ? pending.tier : normalizeTemperature(value);
  const label = `Deal temperature: ${temperatureLabel(shown)}`;
  const box = 'inline-flex h-4 w-4 shrink-0 items-center justify-center';

  if (!onCycle) return <span role="img" aria-label={label} title={label} className={box}><Glyph tier={shown} /></span>;

  const upcoming = temperatureLabel(nextTemperature(shown));
  function click(e: MouseEvent) {
    // On a board card: a click here must not also open the deal.
    e.stopPropagation();
    e.preventDefault();
    if (disabled) return;
    const next = nextTemperature(shown);
    const mine = ++op.current;
    setPending({ tier: next });
    onCycle!(next).catch(() => {}).finally(() => { if (op.current === mine) setPending(null); });
  }
  return (
    <button type="button" disabled={disabled} onClick={click} title={`${label}. Click to set ${upcoming}.`}
      aria-label={`${label}. Click to set ${upcoming}.`} className={`${box} cursor-pointer border-0 bg-transparent p-0 disabled:cursor-default`}>
      <Glyph tier={shown} />
    </button>
  );
}

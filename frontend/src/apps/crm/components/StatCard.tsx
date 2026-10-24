/** A metric tile. Presentational: the parent passes formatted strings; `tone` colours the value. */
export function StatCard({ label, value, sub, tone }: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'good' | 'warn' | 'bad';
}) {
  const color = tone === 'good' ? 'text-sf-green-text' : tone === 'warn' ? 'text-sf-amber-text' : tone === 'bad' ? 'text-sf-red-text' : 'text-sf-ink';
  return (
    <div className="min-w-[132px] flex-[1_1_150px] rounded-lg border border-sf-line bg-sf-card px-4 py-3">
      <div className="text-xs font-medium tracking-wide text-sf-ink-dim uppercase">{label}</div>
      <div className={`mt-1.5 font-display text-2xl leading-tight ${color}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-sf-ink-mute">{sub}</div>}
    </div>
  );
}

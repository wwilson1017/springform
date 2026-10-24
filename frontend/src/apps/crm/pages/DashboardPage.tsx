/**
 * The CRM home: the open pipeline in one sentence, the headline numbers, what needs a touch
 * today, the pipeline by stage (each row opens that column), the deals most worth attention and
 * the latest activity. A first-run card points at import and the first deal until dismissed.
 */
import { Link } from 'react-router';
import { postJson } from '../../../core/api/client';
import { useJson } from '../../../core/api/useJson';
import { formatDate } from '../../../shared/formatDate';
import { LoadError } from '../../../shared/LoadError';
import { dashboardUrl, type Dashboard } from '../api';
import { OPEN_STAGES, STAGE_COLORS, stageLabel } from '../constants';
import { StatCard } from '../components/StatCard';
import { StageBadge, StageDot } from '../components/badges';
import { formatCents } from '../money';
import { card, muted, page, sectionTitle } from '../ui';
import { TodayList } from './TodayPage';

interface Meta { empty: boolean; sample_data_loaded: boolean; onboarding_dismissed: boolean }

export function DashboardPage() {
  const { data, error, reload } = useJson<Dashboard>(dashboardUrl);
  if (error) return <div className={page}><LoadError label="Couldn't load the CRM dashboard" onRetry={reload} /></div>;
  if (!data) return <div className={page}><p className={muted}>Loading…</p></div>;

  // Every open stage, an empty one included, so the funnel's shape reads at a glance.
  const open = OPEN_STAGES.map(stage => data.pipeline_by_stage.find(s => s.stage === stage) ?? { stage, count: 0, total_value_cents: 0 });
  const openCount = open.reduce((n, s) => n + s.count, 0);
  const maxStage = Math.max(1, ...open.map(s => s.total_value_cents));

  return (
    <div className={`${page} flex flex-col gap-6`}>
      <FirstRun />
      <h1 className="m-0 font-display text-2xl leading-tight font-medium text-sf-ink md:text-4xl">
        Pipeline is <span className="text-sf-amber-text">{formatCents(data.total_pipeline_value_cents)}</span>
        <span className="block text-base text-sf-ink-mute md:text-xl">across {openCount} open deal{openCount === 1 ? '' : 's'}.</span>
      </h1>

      <div className="flex flex-wrap gap-3">
        <StatCard label="People" value={data.total_people.toLocaleString()} />
        <StatCard label="Organizations" value={data.total_organizations.toLocaleString()} />
        <StatCard label="Open pipeline" value={formatCents(data.total_pipeline_value_cents)} />
        <StatCard label="Won this month" value={formatCents(data.won_this_month_cents)} tone={data.won_this_month_cents > 0 ? 'good' : undefined} />
      </div>

      <section className={`${card} p-4`}>
        <div className="flex items-baseline justify-between">
          <h2 className={sectionTitle}>Today</h2>
          <Link to="/crm/today" className="text-sm text-sf-accent-text">See all</Link>
        </div>
        <TodayList compact />
      </section>

      <section>
        <h2 className={sectionTitle}>By stage</h2>
        <ul className="m-0 list-none divide-y divide-sf-line border-t border-sf-line p-0">
          {open.map(s => (
            <li key={s.stage}>
              <Link to={`/crm/deals?stage=${s.stage}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 py-3 no-underline md:grid-cols-[150px_1fr_120px_80px]">
                <span className="flex items-center gap-2 text-base text-sf-ink"><StageDot stage={s.stage} />{stageLabel(s.stage)}</span>
                <span className="order-last col-span-2 h-0.5 bg-sf-line md:order-none md:col-span-1">
                  <span className="block h-full" style={{ width: `${Math.max(2, (s.total_value_cents / maxStage) * 100)}%`, background: STAGE_COLORS[s.stage].fill }} />
                </span>
                <span className="text-right font-display text-base text-sf-ink">{formatCents(s.total_value_cents)}</span>
                <span className="hidden text-right text-xs text-sf-ink-mute md:block">{s.count} deal{s.count === 1 ? '' : 's'}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section className={`${card} p-4`}>
          <h2 className={sectionTitle}>Deals to watch</h2>
          {data.top_deals.length === 0 ? <p className={muted}>No open deals past lead yet.</p> : (
            <ul className="m-0 list-none divide-y divide-sf-line p-0">
              {data.top_deals.map(d => (
                <li key={d.id}>
                  <Link to={`/crm/deals/${d.id}`} className="flex items-center gap-3 py-2 text-sm no-underline">
                    <span className="min-w-0 flex-1 truncate text-sf-ink">{d.title}</span>
                    <StageBadge stage={d.stage} />
                    <span className="text-sf-ink-mute">{formatCents(d.value_cents, d.currency)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className={`${card} p-4`}>
          <h2 className={sectionTitle}>Recent activity</h2>
          {data.recent_activity.length === 0 ? <p className={muted}>Nothing logged yet.</p> : (
            <ul className="m-0 list-none divide-y divide-sf-line p-0">
              {data.recent_activity.map(a => (
                <li key={a.id} className="py-2 text-sm">
                  <span className="text-sf-ink">{a.activity}</span>
                  {a.deal_id && <> · <Link to={`/crm/deals/${a.deal_id}`} className="text-sf-accent-text">{a.deal_title}</Link></>}
                  {a.note && <span className="block truncate text-sf-ink-mute">{a.note}</span>}
                  <span className="block text-xs text-sf-ink-dim">{a.actor_name ?? 'Someone'} · {formatDate(a.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function FirstRun() {
  const { data, setData } = useJson<Meta>('/api/crm/meta');
  if (!data || !data.empty || data.onboarding_dismissed) return null;
  const dismiss = () => { postJson<Meta>('/api/crm/meta/dismiss-onboarding').then(setData, () => {}); };
  return (
    <div className={`${card} flex flex-wrap items-center gap-3 p-4 text-sm`}>
      <p className="m-0 flex-1 text-sf-ink">
        Start by <Link to="/crm/import" className="text-sf-accent-text">importing your contacts</Link> or <Link to="/crm/deals" className="text-sf-accent-text">adding a deal</Link>.
      </p>
      <button type="button" onClick={dismiss} className="cursor-pointer border-0 bg-transparent text-sf-ink-dim">Dismiss</button>
    </div>
  );
}

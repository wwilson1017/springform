import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { MarkdownContent } from '../../shared/MarkdownContent';
import { LoadError } from '../../shared/LoadError';
import { ApiError } from '../api/client';
import type { CoreApp } from '../api/types';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { appName, plainSnippet } from './format';
import { inputClass, Page } from './Page';
import type { GuideHit, GuideTopic, GuideTopicBody } from './types';

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** Springform's own topics first, then one group per app in launcher order. */
function groupTopics(topics: GuideTopic[], apps: CoreApp[] | null) {
  const order = ['core', ...(apps ?? []).map(a => a.slug)];
  const rank = (key: string) => (order.indexOf(key) + 1 || order.length + 1);
  const groups = new Map<string, GuideTopic[]>();
  for (const t of topics) {
    groups.set(t.app, [...(groups.get(t.app) ?? []), t]);
  }
  return [...groups].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}

export function GuideIndex() {
  const { apps } = useCoreApps();
  const [q, setQ] = useState('');
  const query = useDebounced(q.trim(), 250);
  const topics = useJson<GuideTopic[]>('/api/core/guide');
  const hits = useJson<GuideHit[]>(query ? `/api/core/guide/search?q=${encodeURIComponent(query)}&limit=20` : null);
  const searching = q.trim() !== '';

  return (
    <Page title="Guide" intro="How this install works, and how to use each app.">
      <label htmlFor="guide-search" className="sr-only">Search the Guide</label>
      <input id="guide-search" type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search the Guide"
        className={`${inputClass} mb-6 w-full`} />

      {searching ? (
        hits.error ? <LoadError label="Couldn't search the Guide" onRetry={hits.reload} />
          : !hits.data || query !== q.trim() ? <p className="text-sm text-sf-ink-dim">Searching…</p>
          : hits.data.length === 0 ? <p className="text-sm text-sf-ink-mute">Nothing in the Guide matches “{query}”.</p>
          : (
            <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
              {hits.data.map(h => (
                <li key={h.slug}>
                  <Link to={`/guide/${h.slug}`} className="block px-4 py-3 no-underline hover:bg-sf-hover">
                    <span className="text-sm font-medium text-sf-ink">{h.title}</span>
                    <span className="ml-2 text-xs text-sf-ink-dim">{appName(apps, h.app)}</span>
                    <span className="mt-1 block text-sm text-sf-ink-mute">{plainSnippet(h.snippet)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )
      ) : topics.error ? <LoadError label="Couldn't load the Guide" onRetry={topics.reload} />
        : !topics.data ? <p className="text-sm text-sf-ink-dim">Loading…</p>
        : groupTopics(topics.data, apps).map(([key, list]) => (
          <section key={key} className="mb-8">
            <h2 className="m-0 mb-3 font-display text-base font-medium text-sf-ink">{appName(apps, key)}</h2>
            <ul className="m-0 grid list-none gap-3 p-0 md:grid-cols-2">
              {list.map(t => (
                <li key={t.slug}>
                  <Link to={`/guide/${t.slug}`}
                    className="block h-full rounded-lg border border-sf-line-strong bg-sf-card px-4 py-3 no-underline hover:bg-sf-hover">
                    <span className="block text-sm font-medium text-sf-ink">{t.title}</span>
                    {t.summary && <span className="mt-1 block text-sm text-sf-ink-mute">{t.summary}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </Page>
  );
}

export function GuideTopicPage() {
  const { slug = '' } = useParams();
  const { apps } = useCoreApps();
  const { data: topic, error, reload } = useJson<GuideTopicBody>(`/api/core/guide/${encodeURIComponent(slug)}`);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
      <Link to="/guide" className="text-sm text-sf-accent-text">← Guide</Link>
      <div className="mt-4">
        {error instanceof ApiError && error.status === 404 ? <p className="text-sf-ink-mute">There's no Guide topic here.</p>
          : error ? <LoadError label="Couldn't load this topic" onRetry={reload} />
          : !topic ? <p className="text-sm text-sf-ink-dim">Loading…</p>
          : (
            <article>
              <p className="m-0 text-xs text-sf-ink-dim">{appName(apps, topic.app)}</p>
              <h1 className="mt-1 mb-2 font-display text-2xl font-medium text-sf-ink">{topic.title}</h1>
              {topic.summary && <p className="mt-0 mb-6 text-sf-ink-soft">{topic.summary}</p>}
              <MarkdownContent content={topic.body_markdown} />
            </article>
          )}
      </div>
    </div>
  );
}

import { Link } from 'react-router';
import { IconSparkle } from './icons';

/** No usable AI key on the install (GET /api/agent/status configured:false). Nothing else waits for one. */
export function ZeroKeyCard({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-2 rounded-lg border border-solid border-sf-line-strong bg-sf-card p-6 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-sf-ai/15 text-sf-ai-text">
        <IconSparkle size={20} aria-hidden />
      </span>
      <h2 className="m-0 font-display text-lg font-medium text-sf-ink">Whisk needs an AI key</h2>
      <p className="m-0 text-sm text-sf-ink-soft">
        Whisk answers with a model from Anthropic or OpenAI, and no key is set up yet. Every other part of
        the app works without one.
      </p>
      {isAdmin ? (
        <Link to="/settings/ai" className="mt-2 rounded-md bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink no-underline">
          Add a key in AI settings
        </Link>
      ) : (
        <p className="m-0 mt-1 text-sm text-sf-ink">Ask an admin to add one.</p>
      )}
    </div>
  );
}

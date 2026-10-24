import { Link } from 'react-router';

export function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-16 text-center">
      <h1 className="m-0 font-display text-2xl font-medium text-sf-ink">Page not found</h1>
      <p className="text-sf-ink-mute">This page doesn't exist, or you don't have access to it.</p>
      <Link to="/" className="text-sf-accent-text">Back to the launcher</Link>
    </div>
  );
}

/** A core screen whose real version arrives in a later wave. */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="m-0 font-display text-2xl font-medium text-sf-ink">{title}</h1>
      <p className="text-sf-ink-mute">{title} are coming in the next wave.</p>
    </div>
  );
}

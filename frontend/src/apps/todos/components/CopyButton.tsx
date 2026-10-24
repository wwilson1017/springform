import { useCopyToClipboard } from '../lib/useCopyToClipboard';

interface Props {
  /** Built lazily — the sheet copies live form state, not the saved row. */
  text: () => string;
  /** What this copies, for screen readers ("Copy the whole todo"). */
  label: string;
}

/**
 * The Copy affordance beside every copyable thing: the links, the AI-tool
 * snippets, and (twice) the edit sheet. Says so when the copy did not happen.
 *
 * Sized for a thumb (36px tall) rather than for the label it sits next to —
 * this is the one control on the sheet a phone user reaches for without meaning
 * to focus a field, so it must not be a mis-tap away from the input beside it.
 */
export function CopyButton({ text, label }: Props) {
  const { copied, failed, copy } = useCopyToClipboard();

  return (
    <button
      type="button"
      onClick={() => void copy(text())}
      aria-label={failed ? `${label} failed. Select the text and copy it.` : label}
      title={label}
      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-display transition-colors ${
        copied
          ? 'border-sf-green text-sf-green-text '
          : failed
            ? 'border-sf-accent text-sf-accent-text'
            : 'border-sf-line-strong text-sf-ink-dim hover:bg-sf-hover'
      }`}
    >
      <span aria-hidden="true">{copied ? '✓' : failed ? '!' : '⧉'}</span>
      {copied ? 'Copied' : failed ? 'Copy failed — select and copy' : 'Copy'}
    </button>
  );
}

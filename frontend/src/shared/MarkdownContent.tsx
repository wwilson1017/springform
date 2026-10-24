import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Markdown (GitHub flavour) in the app's type and colour tokens. Raw HTML in the source is
 * not rendered (react-markdown's default), so model or user text cannot inject markup.
 * Links open in a new tab. Lifted from Chatty's MarkdownContent; code highlighting dropped.
 */
export function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="mb-2 mt-4 text-xl font-semibold text-sf-ink first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-3 text-lg font-semibold text-sf-ink first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-3 text-base font-semibold text-sf-ink first:mt-0">{children}</h3>,
        p: ({ children }) => <p className="mb-3 mt-0 leading-relaxed last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="mb-3 ml-5 mt-0 list-disc space-y-1 p-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-3 ml-5 mt-0 list-decimal space-y-1 p-0">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-sf-accent-text underline">{children}</a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-3 ml-0 border-0 border-l-2 border-solid border-sf-line-strong pl-4 italic text-sf-ink-soft">{children}</blockquote>
        ),
        code: ({ className, children }) => {
          const block = className?.includes('language-') || (typeof children === 'string' && children.includes('\n'));
          return block
            ? <code className={className}>{children}</code>
            : <code className="rounded bg-sf-raised px-1.5 py-0.5 font-mono text-[0.9em]">{children}</code>;
        },
        pre: ({ children }) => (
          <pre className="my-3 overflow-x-auto rounded-md bg-sf-raised p-4 font-mono text-sm text-sf-ink">{children}</pre>
        ),
        table: ({ children }) => (
          <div className="my-3 overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-sf-raised">{children}</thead>,
        th: ({ children }) => <th className="border border-solid border-sf-line-strong px-3 py-2 text-left text-xs font-semibold">{children}</th>,
        td: ({ children }) => <td className="border border-solid border-sf-line-strong px-3 py-2">{children}</td>,
        hr: () => <hr className="my-4 border-0 border-t border-solid border-sf-line-strong" />,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

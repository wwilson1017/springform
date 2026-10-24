// The two presentations of the menu, top row and phone bottom bar, both drawn from the one
// list definition in ../menu.ts. TodoShell picks which to mount.
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { PRIMARY, SECONDARY, overflowHidden, todoPath, type ListItem } from '../menu';

interface MenuProps {
  /** The current page's key; anything not in the menu (e.g. 'connect') marks nothing. */
  active: string;
  inboxCount: number;
}

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-sf-accent';

function Label({ item, inboxCount }: { item: ListItem; inboxCount: number }) {
  return (
    <>
      {item.label}
      {item.key === 'inbox' && inboxCount > 0 && (
        <span className="ml-1.5 rounded-full bg-sf-accent px-1.5 py-0.5 text-xs font-bold leading-none text-sf-accent-ink">
          {inboxCount}
        </span>
      )}
    </>
  );
}

// ── "More": a disclosure button over a short list of links ──────────────────

const primaryCls = (current: boolean) =>
  `whitespace-nowrap border-b-[3px] -mb-px px-2.5 py-2 text-base ${FOCUS} ${current
    ? 'border-sf-accent font-semibold text-sf-ink'
    : 'border-transparent text-sf-ink-dim hover:text-sf-ink'}`;

const secondaryCls = (current: boolean) =>
  `rounded px-[7px] py-1.5 text-[0.8125rem] ${FOCUS} ${current
    ? 'font-bold text-sf-ink'
    : 'text-sf-ink-dim hover:text-sf-ink'}`;

// The bar sits on the screen edge, so its focus ring is drawn inside the item.
const phoneCls = (current: boolean) =>
  `flex min-h-14 min-w-0 flex-1 items-center justify-center border-t-[3px] -mt-px px-0.5 text-xs ${FOCUS} -outline-offset-2 ${current
    ? 'border-sf-accent font-semibold text-sf-ink'
    : 'border-transparent text-sf-ink-dim'}`;

const MORE_LABEL = <>More<span aria-hidden="true"> ▾</span></>;

function MoreMenu({ items, active, phone = false }: { items: ListItem[]; active: string; phone?: boolean }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setOpen(false);
      button.current?.focus();
    };
    // A press or keyboard focus anywhere outside closes it, so tabbing on past the
    // last item never leaves it open over the page.
    const onOutside = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onOutside);
    document.addEventListener('focusin', onOutside);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('focusin', onOutside);
    };
  }, [open]);

  // On the phone every secondary list is in here, so the button stands in for the
  // current one when it is among them: marked current in the bar's set of items
  // ("true"), while the link inside keeps "page".
  const holdsCurrent = items.some(i => i.key === active);

  return (
    <div ref={wrap} className={phone ? 'flex min-w-0 flex-1' : 'relative'}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-current={holdsCurrent ? 'true' : undefined}
        onClick={() => setOpen(o => !o)}
        className={phone ? phoneCls(holdsCurrent) : secondaryCls(holdsCurrent)}
      >
        {phone ? 'More' : MORE_LABEL}
      </button>
      {open && (
        <div
          id={panelId}
          className={`z-40 border border-sf-line-strong bg-sf-card shadow-lg ${phone
            ? 'fixed inset-x-2 bottom-[calc(var(--bottom-bar)+0.5rem)] rounded-xl p-1.5'
            : 'absolute right-0 top-full mt-1 min-w-36 rounded-lg p-1'}`}
        >
          {items.map(item => {
            const current = item.key === active;
            return (
              <Link
                key={item.key}
                to={todoPath(item.sub)}
                aria-current={current ? 'page' : undefined}
                onClick={() => setOpen(false)}
                className={`block rounded-lg text-sf-ink hover:bg-sf-hover ${FOCUS} ${
                  phone ? 'px-3 py-3 text-base' : 'px-3 py-2 text-sm'
                } ${current ? 'bg-sf-bg font-semibold' : ''}`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Top menu: primary tabs left, secondary small on the right ───────────────

const SECONDARY_ROW = 'flex items-center whitespace-nowrap border-l border-sf-line-strong pl-1.5';

export function TopMenu({ active, inboxCount }: MenuProps) {
  const slot = useRef<HTMLDivElement>(null);
  const ruler = useRef<HTMLDivElement>(null);
  const [hidden, setHidden] = useState<number[]>([]);
  const current = SECONDARY.findIndex(l => l.key === active);

  // Priority-plus: the ruler is an invisible copy of the full secondary run plus
  // "More", so every width is known whether or not the item is showing.
  useLayoutEffect(() => {
    const s = slot.current, r = ruler.current;
    if (!s || !r) return;
    const measure = () => {
      const widths = [...r.children].map(c => (c as HTMLElement).offsetWidth);
      const more = widths.pop() ?? 0;
      const chrome = r.offsetWidth - more - widths.reduce((a, b) => a + b, 0); // divider + padding
      const next = overflowHidden(widths, s.clientWidth - chrome, more, current);
      setHidden(prev => (prev.join() === next.join() ? prev : next));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(s);
    ro.observe(r);
    return () => ro.disconnect();
  }, [current]);

  return (
    <div className="mt-3 flex items-stretch border-b border-sf-line-strong">
      <nav aria-label="Main lists" className="flex shrink-0 gap-0.5">
        {PRIMARY.map(item => (
          <Link
            key={item.key}
            to={todoPath(item.sub)}
            aria-current={item.key === active ? 'page' : undefined}
            className={primaryCls(item.key === active)}
          >
            <Label item={item} inboxCount={inboxCount} />
          </Link>
        ))}
      </nav>
      <div ref={slot} className="relative ml-3 flex min-w-0 flex-1 items-center justify-end">
        <nav aria-label="Other lists" className={SECONDARY_ROW}>
          {SECONDARY.map((item, i) => !hidden.includes(i) && (
            <Link
              key={item.key}
              to={todoPath(item.sub)}
              aria-current={i === current ? 'page' : undefined}
              className={secondaryCls(i === current)}
            >
              {item.label}
            </Link>
          ))}
          {hidden.length > 0 && (
            <MoreMenu items={hidden.map(i => SECONDARY[i])} active={active} />
          )}
        </nav>
        {/* Anchored right so its overflow runs left, never widening the page. */}
        <div
          ref={ruler}
          aria-hidden="true"
          className={`${SECONDARY_ROW} pointer-events-none invisible absolute right-0 top-0`}
        >
          {SECONDARY.map((item, i) => (
            <span key={item.key} className={secondaryCls(i === current)}>{item.label}</span>
          ))}
          <span className={secondaryCls(false)}>{MORE_LABEL}</span>
        </div>
      </div>
    </div>
  );
}

// ── Phone: primary five in a fixed bottom bar, the rest behind More ─────────

export function BottomBar({ active, inboxCount }: MenuProps) {
  return (
    <nav
      aria-label="Main lists"
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-sf-line-strong bg-sf-card pb-[env(safe-area-inset-bottom)]"
    >
      {PRIMARY.map(item => (
        <Link
          key={item.key}
          to={todoPath(item.sub)}
          aria-current={item.key === active ? 'page' : undefined}
          className={phoneCls(item.key === active)}
        >
          <Label item={item} inboxCount={inboxCount} />
        </Link>
      ))}
      <MoreMenu items={SECONDARY} active={active} phone />
    </nav>
  );
}

import type { MentionPickerState } from './useMentionPicker';

/** The `@` suggestions under a textarea. Render inside a `relative` wrapper around it. */
export function MentionPicker({ id, picker }: { id: string; picker: MentionPickerState }) {
  if (picker.users.length === 0) return null;
  return (
    <ul id={id} role="listbox" aria-label="Mention a teammate"
      className="absolute left-2 top-full z-30 m-0 mt-0.5 min-w-52 max-w-80 list-none rounded-md border border-sf-line-strong bg-sf-card p-1 shadow-lg">
      {picker.users.map((user, i) => (
        <li key={user.id} id={`${id}-${i}`} role="option" aria-selected={i === picker.index}
          // mousedown, not click: focus stays in the textarea, so the caret survives.
          onMouseDown={e => { e.preventDefault(); picker.choose(user); }}
          onMouseEnter={() => picker.hover(i)}
          className={`cursor-pointer rounded px-2.5 py-1.5 text-sm text-sf-ink ${i === picker.index ? 'bg-sf-hover' : ''}`}>
          {user.name}
        </li>
      ))}
    </ul>
  );
}

// Test helper: a React root whose every render sits inside a MemoryRouter, for components that
// link (the edit sheet's "Open page") but are tested on their own. Imported by tests only.
import type { ReactNode } from 'react';
import type { Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';

export function routed(root: Root): Root {
  return {
    render: (children: ReactNode) => root.render(<MemoryRouter>{children}</MemoryRouter>),
    unmount: () => root.unmount(),
  };
}

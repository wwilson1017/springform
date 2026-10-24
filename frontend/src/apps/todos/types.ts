// The Todos API's shapes, from the backend's response models (types.gen.ts). The names are the
// donor's (Todo, TodoProject, ...), so the lifted screens read the same.
import type { components } from '../../core/api/types.gen';

type S = components['schemas'];

export type Todo = S['Item'];
export type TodoStatus = Todo['status'];
export type Visibility = Todo['visibility'];
export type TodoProject = S['Project'];
export type TodoProjectStatus = TodoProject['status'];
export type TodoArea = S['Area'];
export type TodoFilters = S['Filters'];
export type Member = S['NamedId'];
export type Changes = S['Changes'];
export type Review = S['Review'];
export type ReviewStatus = S['ReviewStatus'];

// Request bodies. The generated In models mark defaulted fields required, so they are partial
// here; the server fills the defaults and refuses unknown keys with a 422.
export type ItemIn = Partial<S['ItemIn']> & { title: string };
export type ItemPatch = Partial<S['ItemPatch']>;
export type ProjectIn = Partial<S['ProjectIn']> & { name: string };
export type ProjectPatch = Partial<S['ProjectPatch']>;
export type AreaIn = Partial<S['AreaIn']> & { name: string };
export type AreaPatch = Partial<S['AreaPatch']>;

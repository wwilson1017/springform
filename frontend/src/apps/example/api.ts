import { fetchJson, patchJson, postJson } from '../../core/api/client';

export interface Widget {
  id: number;
  name: string;
  color: string | null;
  owner_user_id: number;
  person_id: number | null;
  is_private: boolean;
  created_at: string;
  updated_at: string;
}

export type WidgetInput = Partial<Pick<Widget, 'name' | 'color' | 'is_private' | 'person_id'>>;

/** The timeline and attachments entity type for a widget. */
export const WIDGET_ENTITY = 'example.widget';

export const widgetsUrl = (personId?: number) =>
  personId === undefined ? '/api/example/widgets' : `/api/example/widgets?person_id=${personId}`;
export const widgetUrl = (id: number | string) => `/api/example/widgets/${id}`;

export const getWidget = (id: number) => fetchJson<Widget>(widgetUrl(id));
export const createWidget = (body: WidgetInput & { name: string }) => postJson<Widget>(widgetsUrl(), body);
export const updateWidget = (id: number, body: WidgetInput) => patchJson<Widget>(widgetUrl(id), body);

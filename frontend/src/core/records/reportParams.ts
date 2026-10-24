/**
 * A report's params form state. Values are kept as the strings a query string carries ("" is
 * absent); the server coerces them to the schema's types and answers 422 with the reason.
 */
import type { ReportParam, ReportParamsSchema } from './types';

export type ParamValues = Record<string, string>;

export const paramEntries = (schema: ReportParamsSchema | null): Array<[string, ReportParam]> =>
  Object.entries(schema?.properties ?? {});

export const isRequired = (schema: ReportParamsSchema | null, name: string) => (schema?.required ?? []).includes(name);

/** Each param's default, or "". */
export function initialParams(schema: ReportParamsSchema | null): ParamValues {
  return Object.fromEntries(paramEntries(schema).map(([name, p]) => [name, p.default === undefined ? '' : String(p.default)]));
}

/** Required params still empty, by title. */
export function missingParams(schema: ReportParamsSchema | null, values: ParamValues): string[] {
  return paramEntries(schema).filter(([name]) => isRequired(schema, name) && !values[name]).map(([name, p]) => p.title ?? name);
}

/** The query string for a run or the CSV link: set values only. */
export function paramsQuery(values: ParamValues): string {
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v !== '')).toString();
}

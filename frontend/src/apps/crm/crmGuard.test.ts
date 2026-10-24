// @vitest-environment node
// The CRM speaks the shared directory's words: people and organizations, never the donor's
// contacts and companies. A leftover `contact_id`/`company_id` would compile against a loose
// type and silently send a field the API rejects.
import { describe, expect, it } from 'vitest';

const sources = import.meta.glob<string>(['./**/*.{ts,tsx}', '!./crmGuard.test.ts'], { query: '?raw', import: 'default', eager: true });
const FORBIDDEN = /\b(contact_id|company_id)\b/;

const offenders = (files: Record<string, string>) => Object.keys(files).filter(f => FORBIDDEN.test(files[f]));

describe('CRM grep guard', () => {
  it('reached the real CRM sources', () => {
    expect(Object.keys(sources)).toContain('./pages/PipelinePage.tsx');
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('apps/crm contains no contact_id or company_id', () => {
    expect(offenders(sources)).toEqual([]);
  });

  it('is falsifiable', () => {
    expect(offenders({ 'a.ts': 'body.contact_id = 1', 'b.ts': '{ company_id: 2 }' })).toEqual(['a.ts', 'b.ts']);
    expect(offenders({ 'c.ts': 'person_id, organization_id, contact_identity' })).toEqual([]);
  });
});

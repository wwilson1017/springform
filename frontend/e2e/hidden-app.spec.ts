import { expect, test } from './fixtures';

// Hiding an app is install-wide, so this runs on the second backend (no other spec there uses
// Example) and in the desktop project only (playwright.config.ts).
test.use({ baseURL: process.env.E2E_ZERO_KEY_URL ?? 'http://127.0.0.1:8161' });

test('a hidden app stays on the admin launcher, marked, and leaves the member launcher', async ({ admin, member }) => {
  // A fresh install starts Example hidden (hidden_by_default); show it so the admin can hide it.
  await admin.api.patch('/api/core/apps/example', { hidden: false });
  await admin.page.goto('/settings/apps');
  await admin.page.getByRole('button', { name: 'Hide Example' }).click();
  await expect(admin.page.getByRole('button', { name: 'Show Example' })).toBeVisible();
  try {
    await admin.page.goto('/');
    await expect(admin.page.getByRole('main').getByRole('link', { name: 'Example' })).toContainText('hidden');

    await member.page.goto('/');
    await expect(member.page.getByRole('main').getByRole('listitem')).toHaveText([/^CRM/, /^Todos/]);
    await expect(member.page.getByRole('banner').getByRole('link', { name: 'Example' })).toHaveCount(0);
    expect((await member.api.get<Array<{ slug: string }>>('/api/core/apps')).map(a => a.slug)).toEqual(['crm', 'todos']);
  } finally {
    await admin.api.patch('/api/core/apps/example', { hidden: true });
  }
});

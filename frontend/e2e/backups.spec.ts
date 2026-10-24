import { expect, test } from './fixtures';
import { serverNow } from './totp';

interface Overview { sets: Array<{ stamp: string; manifest_ok: boolean }>; last_run: { status: string } | null }

// Desktop project only (playwright.config.ts): under a frozen clock every set gets the same
// stamp, so a second "Back up now" on one boot fails (finding F1). The phone layout is checked
// here by resizing instead.
test('Back up now writes a complete recovery set', async ({ admin }) => {
  const { page, api } = admin;
  const before = (await api.get<Overview>('/api/core/backups')).sets.length;
  const stamp = serverNow().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');

  await page.goto('/backups');
  await expect(page.getByRole('heading', { name: 'Backups', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Back up now' }).click();
  await expect(page.getByText('Backup written')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Last run' })).toContainText('Succeeded');
  const row = page.getByRole('row').filter({ hasText: stamp });
  await expect(row).toContainText('Complete');

  const overview = await api.get<Overview>('/api/core/backups');
  expect(overview.sets).toHaveLength(before + 1);
  expect(overview.sets).toContainEqual(expect.objectContaining({ stamp, manifest_ok: true }));
  expect(overview.last_run?.status).toBe('ok');
  const download = await api.request.get(`/api/core/backups/${stamp}/download`);
  expect(download.ok()).toBe(true);
  expect((await download.body()).subarray(0, 15).toString()).toBe('SQLite format 3');

  // At phone width the set's links move under its stamp.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row.getByRole('link', { name: 'Download' })).toBeVisible();
});

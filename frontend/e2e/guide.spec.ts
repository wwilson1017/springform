import { expect, test } from './fixtures';

test('the Guide opens a topic, and search finds one', async ({ member }) => {
  const { page } = member;
  await page.goto('/guide');
  await expect(page.getByRole('heading', { name: 'Guide', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'CRM', level: 2 })).toBeVisible();
  await page.getByRole('link', { name: /^Getting started/ }).click();
  await expect(page.getByRole('heading', { name: 'Getting started', level: 1 })).toBeVisible();
  await expect(page.getByText('setup token').first()).toBeVisible();

  await page.getByRole('link', { name: '← Guide' }).click();
  const search = page.getByRole('searchbox', { name: 'Search the Guide' });
  await search.fill('restore');
  await page.getByRole('link', { name: /^Backups and restore/ }).click();
  await expect(page.getByRole('heading', { name: 'Backups and restore', level: 1 })).toBeVisible();

  await page.goto('/guide');
  await search.fill('zzqqxx');
  await expect(page.getByText('Nothing in the Guide matches “zzqqxx”.')).toBeVisible();
});

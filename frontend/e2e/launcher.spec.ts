import { expect, openMenu, test } from './fixtures';

const ROLES = { admin: { button: 'Admin', menu: ['Guide', 'Requests', 'Jobs', 'Backups'] }, member: { button: 'Member', menu: ['Guide', 'Requests'] } };
const ADMIN_ONLY = ['Jobs', 'Backups'];

for (const [role, { button, menu }] of Object.entries(ROLES)) {
  test(`the role picker signs in as ${role} and the launcher and menu follow the role`, async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();

    const apps = await (await page.request.get('/api/core/apps')).json() as Array<{ name: string; roles: string[] }>;
    expect(apps.map(a => a.name).sort()).toEqual(['CRM', 'Example', 'Todos']);
    const tiles = page.getByRole('main').getByRole('listitem');
    await expect(tiles).toHaveCount(apps.length);
    for (const app of apps) await expect(page.getByRole('main').getByRole('link', { name: app.name, exact: true })).toBeVisible();

    const { entry } = await openMenu(page);
    for (const name of menu) await expect(entry(name)).toBeVisible();
    for (const name of ADMIN_ONLY.filter(n => !menu.includes(n))) await expect(entry(name)).toHaveCount(0);
    await entry('Settings').click();
    await expect(page).toHaveURL(/\/settings\/account$/);
  });
}

test('a member is kept out of the admin-only pages', async ({ member }) => {
  const { page } = member;
  for (const path of ['/jobs', '/backups']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe('/');
  }
  expect((await page.request.get('/api/core/jobs')).status()).toBe(403);
});

import { expect, test, type Session } from './fixtures';

const MEMBER = ['Account', 'Notifications', 'Workspace', 'Apps', 'MCP', 'Todos'];
const ADMIN = [
  'Account', 'Notifications', 'Workspace', 'Apps', 'MCP', 'Users', 'Records', 'Sign-in', 'Integrations', 'Data', 'AI',
  'MCP servers', 'CRM', 'Todos', 'Example',
];

async function sections({ page }: Session) {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/settings\/account$/);
  return page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link');
}

test("an admin sees every section, including the example app's card", async ({ admin }) => {
  await expect(await sections(admin)).toHaveText(ADMIN);
  const { page } = admin;
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Example' }).click();
  await expect(page.getByRole('heading', { name: 'Example', level: 2 })).toBeVisible();
  await expect(page.getByText('Nothing to configure. This card comes from')).toBeVisible();
});

test('a member sees only the sections with a card for members', async ({ member }) => {
  await expect(await sections(member)).toHaveText(MEMBER);
  const { page } = member;
  await expect(page.getByRole('heading', { name: 'Security', level: 2 })).toBeVisible();
  // A deep link to an admin-only section lands back on the member's first section.
  await page.goto('/settings/example');
  await expect(page).toHaveURL(/\/settings\/account$/);
  await expect(page.getByText('Nothing to configure. This card comes from')).toHaveCount(0);
});

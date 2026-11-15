import { expect, test, type Session } from './fixtures';

// Core's and the upstream apps' sections. A fork's own apps may add more, so these are subset
// checks, never the exact list (#18).
const MEMBER = ['Account', 'Notifications', 'Workspace', 'Apps', 'MCP', 'Todos'];
const ADMIN_ONLY = ['Users', 'Records', 'Sign-in', 'Integrations', 'Data', 'AI', 'MCP servers', 'CRM', 'Example'];

async function sections({ page }: Session) {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/settings\/account$/);
  const links = page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link');
  return () => links.allInnerTexts();
}

test("an admin sees every section, including the example app's card", async ({ admin }) => {
  await expect.poll(await sections(admin)).toEqual(expect.arrayContaining([...MEMBER, ...ADMIN_ONLY]));
  const { page } = admin;
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Example' }).click();
  await expect(page.getByRole('heading', { name: 'Example', level: 2 })).toBeVisible();
  await expect(page.getByText('Nothing to configure. This card comes from')).toBeVisible();
});

test('a member sees only the sections with a card for members', async ({ member }) => {
  const labels = await sections(member);
  await expect.poll(labels).toEqual(expect.arrayContaining(MEMBER));
  expect((await labels()).filter(label => ADMIN_ONLY.includes(label))).toEqual([]);
  const { page } = member;
  await expect(page.getByRole('heading', { name: 'Security', level: 2 })).toBeVisible();
  // A deep link to an admin-only section lands back on the member's first section.
  await page.goto('/settings/example');
  await expect(page).toHaveURL(/\/settings\/account$/);
  await expect(page.getByText('Nothing to configure. This card comes from')).toHaveCount(0);
});

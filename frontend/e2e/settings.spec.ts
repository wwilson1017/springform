import { expect, test, type Session } from './fixtures';

// Section ids (`/settings/<id>`) of core and the upstream apps. A fork's own apps may add more,
// and an app's label is just its name, so these are subset checks on ids, never the exact list (#18).
const MEMBER = ['account', 'notifications', 'workspace', 'apps', 'mcp', 'todos'];
const ADMIN_ONLY = [
  'users',
  'records',
  'signin',
  'integrations',
  'data',
  'ai',
  'mcp_servers',
  'gtd-suite',
  'crm',
  'example',
];

async function sections({ page }: Session) {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/settings\/account$/);
  const links = page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link');
  return () => links.evaluateAll((as) => as.map((a) => a.getAttribute('href')?.replace('/settings/', '')));
}

test("an admin sees every section, including the example app's card", async ({ admin }) => {
  await expect.poll(await sections(admin)).toEqual(expect.arrayContaining([...MEMBER, ...ADMIN_ONLY]));
  const { page } = admin;
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Example' }).click();
  await expect(page.getByRole('heading', { name: 'Example', level: 2 })).toBeVisible();
  await expect(page.getByText('Nothing to configure. This card comes from')).toBeVisible();
});

test('a member sees only the sections with a card for members', async ({ member }) => {
  const ids = await sections(member);
  await expect.poll(ids).toEqual(expect.arrayContaining(MEMBER));
  expect((await ids()).filter((id) => id && ADMIN_ONLY.includes(id))).toEqual([]);
  const { page } = member;
  await expect(page.getByRole('heading', { name: 'Security', level: 2 })).toBeVisible();
  // A deep link to an admin-only section lands back on the member's first section.
  await page.goto('/settings/example');
  await expect(page).toHaveURL(/\/settings\/account$/);
  await expect(page.getByText('Nothing to configure. This card comes from')).toHaveCount(0);
});

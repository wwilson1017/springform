import { expect, test, unique } from './fixtures';

interface Todo { id: number; title: string; status: string; visibility: string }

test('a todo added and shared with the team is seen and completed by the other role', async ({ admin, member }) => {
  const title = unique('Smoke todo');
  const search = `/todos/search?q=${encodeURIComponent(title)}`;
  const find = async () => (await admin.api.get<Todo[]>(`/api/todos/items?search=${encodeURIComponent(title)}`))[0];

  const a = admin.page;
  await a.goto('/todos');
  await a.getByLabel('Add a todo').fill(title);
  await a.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(a.getByLabel('Add a todo')).toHaveValue('');
  await expect.poll(find).toMatchObject({ title, status: 'inbox', visibility: 'private' });

  // Only its owner sees a private todo.
  await member.page.goto(search);
  await expect(member.page.getByText('No matches', { exact: true })).toBeVisible();

  await a.goto(search);
  await a.getByText(title, { exact: true }).click();
  await expect(a.getByRole('heading', { name: 'Edit todo' })).toBeVisible();
  await a.getByRole('radio', { name: 'Team' }).click();
  await a.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(a.getByRole('heading', { name: 'Edit todo' })).toBeHidden();
  await expect(a.getByText(`Team · ${admin.user.name}`)).toBeVisible();
  await expect.poll(find).toMatchObject({ visibility: 'team' });

  const m = member.page;
  await m.reload();
  const row = m.locator('div', { has: m.getByText(title, { exact: true }) }).filter({ has: m.getByRole('checkbox') }).last();
  await expect(row.getByText(`Team · ${admin.user.name}`)).toBeVisible();
  await row.getByRole('checkbox', { name: 'Mark done' }).click();
  await expect.poll(find).toMatchObject({ status: 'done' });

  await a.goto('/todos/done');
  await expect(a.getByText(title, { exact: true })).toBeVisible();
});

import { expect, test, unique } from './fixtures';

// The backend runs with AGENT_FAKE_PROVIDER=1 (scripts/e2e.sh): it echoes a message, and
// `/tool <name> <json>` makes it call that tool.
test('Whisk answers, proposes a write, and runs it on Approve', async ({ admin }) => {
  const { page, api } = admin;
  const name = unique('Whisked widget');
  await page.goto('/whisk');
  const input = page.getByRole('textbox', { name: 'Message Whisk' });

  await input.fill('Hello Whisk');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('You said: Hello Whisk')).toBeVisible();

  await input.fill(`/tool example_create_widget ${JSON.stringify({ name })}`);
  await input.press('Enter');
  const card = page.getByTestId('tool-confirm-card');
  await expect(card).toContainText('Needs your approval');
  await expect(card).toContainText('example_create_widget');
  await expect(card).toContainText(name);
  expect((await api.get<Array<{ name: string }>>('/api/example/widgets')).map(w => w.name)).not.toContain(name);

  await card.getByRole('button', { name: 'Approve' }).click();
  await expect(card).toContainText('Done');
  await expect(card.getByRole('button', { name: 'Approve' })).toHaveCount(0);
  await expect.poll(async () => (await api.get<Array<{ name: string }>>('/api/example/widgets')).map(w => w.name)).toContain(name);
});

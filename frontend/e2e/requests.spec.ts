import { expect, SAME_ORIGIN, test, unique } from './fixtures';

test('the Requests form validates, and says so when GitHub is not connected', async ({ member }) => {
  const { page, api } = member;
  const title = unique('Show the delivery date');
  await page.goto('/requests');
  await expect(page.getByText("Requests aren't connected to GitHub yet").first()).toBeVisible();
  await page.getByRole('button', { name: 'New request' }).click();

  const form = page.getByRole('form', { name: 'New request' });
  const send = form.getByRole('button', { name: 'Send request' });
  await expect(send).toBeDisabled();
  await form.getByLabel('Title').fill('   ');
  await expect(send).toBeDisabled();
  await form.getByLabel('Title').fill(title);
  await form.getByLabel('About').selectOption({ label: 'Todos' });
  await form.getByLabel('Description').fill('On the order list, next to the customer.');
  await expect(send).toBeEnabled();
  await send.click();
  await expect(form.getByRole('alert')).toContainText("Not sent. Requests aren't connected to GitHub yet");
  expect((await api.get<Array<{ title: string }>>('/api/core/requests?state=all')).map(r => r.title)).not.toContain(title);

  // The server's own checks, which the form's controls keep a person from reaching.
  for (const [body, detail] of [
    [{ title: ' ' }, 'title: must be 1-200 characters'],
    [{ title, app: 'nope' }, "app: 'nope' is not an installed app"],
  ] as const) {
    const res = await api.request.post('/api/core/requests', { data: body, headers: SAME_ORIGIN });
    expect(res.status()).toBe(422);
    expect(await res.json()).toEqual({ detail });
  }
});

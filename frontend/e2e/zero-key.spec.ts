import { expect, SAME_ORIGIN, test } from './fixtures';

// A second backend with no AI key and no fake provider (scripts/e2e.sh boots it).
test.use({ baseURL: process.env.E2E_ZERO_KEY_URL ?? 'http://127.0.0.1:8161' });

test('with no AI key Whisk shows the zero-key card, and the rest of the app still works', async ({ admin, member }) => {
  expect(await admin.api.get('/api/agent/status')).toMatchObject({ configured: false });

  await admin.page.goto('/whisk');
  await expect(admin.page.getByRole('heading', { name: 'Whisk needs an AI key' })).toBeVisible();
  await admin.page.getByRole('link', { name: 'Add a key in AI settings' }).click();
  await expect(admin.page).toHaveURL(/\/settings\/ai$/);
  await expect(admin.page.getByRole('heading', { name: 'Providers', level: 2 })).toBeVisible();

  await member.page.goto('/whisk');
  await expect(member.page.getByRole('heading', { name: 'Whisk needs an AI key' })).toBeVisible();
  await expect(member.page.getByText('Ask an admin to add one.')).toBeVisible();
  await expect(member.page.getByRole('textbox', { name: 'Message Whisk' })).toHaveCount(0);
  const chat = await member.api.request.post('/api/agent/chat', { data: { message: 'hello' }, headers: SAME_ORIGIN });
  expect(chat.status()).toBe(400);
  expect(await chat.json()).toEqual({ detail: 'no_provider' });

  await member.page.goto('/');
  await expect(member.page.getByRole('heading', { name: 'Apps' })).toBeVisible();
});

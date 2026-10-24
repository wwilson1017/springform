import { expect, SAME_ORIGIN, test, unique, type User } from './fixtures';
import { serverNow, totp } from './totp';

test('the password form renders and refuses a wrong password', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByText('Sign in to continue.')).toBeVisible();
  await page.getByLabel('Email').fill('preview-admin@example.com');
  await page.getByLabel('Password', { exact: true }).fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toHaveText("That email and password don't match an account.");
  expect((await page.request.get('/api/me')).status()).toBe(401);
});

test('an invited user sets a password, turns on 2FA, and then signs in with a code', async ({ admin, page }) => {
  const email = `${unique('totp').replace(/\W+/g, '-')}@example.com`;
  const password = 'correct horse battery';
  const { invite_url } = await admin.api.post<{ invite_url: string }>('/api/auth/users', { email, name: 'Totp Tester', role: 'member' });

  await page.goto(new URL(invite_url).pathname);
  await expect(page.getByText(email)).toBeVisible();
  await page.getByLabel('Choose a password').fill(password);
  await page.getByLabel('Confirm password').fill(password);
  await page.getByRole('button', { name: 'Set password and sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();

  await page.goto('/settings/account');
  await page.getByRole('button', { name: 'Set up two-factor' }).click();
  await expect(page.getByRole('img', { name: 'QR code for your authenticator app' })).toBeVisible();
  const secret = await page.getByLabel('Setup key').inputValue();
  // The server reads its frozen clock and refuses a step it has seen, so enrol on the step
  // before "now" and sign in on "now".
  await page.getByLabel('Code from the app').fill(totp(secret, serverNow(), -1));
  await page.getByRole('button', { name: 'Turn on' }).click();
  await expect(page.getByRole('list', { name: 'Backup codes' }).getByRole('listitem')).toHaveCount(10);
  await page.getByRole('button', { name: "I've saved them" }).click();
  await expect(page.getByText('Signing in asks for a code from your authenticator app.')).toBeVisible();

  await page.request.post('/api/auth/logout', { headers: SAME_ORIGIN });
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Two-factor authentication' })).toBeVisible();
  await page.getByLabel('Authentication code').fill(totp(secret, serverNow()));
  await page.getByRole('button', { name: 'Verify' }).click();
  await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();
  expect((await (await page.request.get('/api/me')).json() as User).email).toBe(email);
  expect(await (await page.request.get('/api/auth/totp')).json()).toMatchObject({ enabled: true });
});

test('Continue with Google signs in through the preview stub', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Continue with Google' }).click();
  await expect(page.getByRole('heading', { name: 'Choose an account' })).toBeVisible();
  await page.getByRole('link', { name: 'preview-member@example.com' }).click();
  await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();
  expect(await (await page.request.get('/api/me')).json()).toMatchObject({ email: 'preview-member@example.com', role: 'member' });
});

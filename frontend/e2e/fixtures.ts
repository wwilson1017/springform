import { test as base, expect, type APIRequestContext, type APIResponse, type Browser, type Page } from '@playwright/test';

export type Role = 'admin' | 'member';
export interface User { id: number; email: string; name: string; role: Role }

/** A browser's fetch sends this itself; a cookie-authenticated call without it is refused as cross-site. */
export const SAME_ORIGIN = { 'Sec-Fetch-Site': 'same-origin' };

async function body<T>(res: APIResponse, what: string): Promise<T> {
  if (!res.ok()) throw new Error(`${what} -> ${res.status()} ${await res.text()}`);
  return (res.status() === 204 ? null : await res.json()) as T;
}

/** JSON calls with a context's session cookie, for setup data and for checking API state. */
export class Api {
  constructor(readonly request: APIRequestContext) {}
  get<T>(path: string) { return this.request.get(path).then(r => body<T>(r, `GET ${path}`)); }
  post<T>(path: string, data?: unknown) {
    return this.request.post(path, { data, headers: SAME_ORIGIN }).then(r => body<T>(r, `POST ${path}`));
  }
  patch<T>(path: string, data: unknown) {
    return this.request.patch(path, { data, headers: SAME_ORIGIN }).then(r => body<T>(r, `PATCH ${path}`));
  }
}

/** A signed-in browser context: its page, its API and who it is. */
export interface Session { page: Page; api: Api; user: User }

/** The preview role picker's call (`POST /api/auth/preview`); the cookie lands in the page's context. */
export async function signIn(page: Page, role: Role): Promise<User> {
  return (await body<{ user: User }>(await page.request.post('/api/auth/preview', { data: { role } }), 'preview sign-in')).user;
}

/** Opens the menu pages (Guide, Backups, …): the drawer on a phone, the user menu on a desktop.
 *  Returns where its entries are; they are links in the drawer and menu items in the user menu. */
export async function openMenu(page: Page) {
  const drawer = page.getByRole('button', { name: 'Open menu' });
  const userMenu = page.locator('header button[aria-haspopup="menu"]');
  await expect(drawer.or(userMenu)).toBeVisible();
  if (await drawer.isVisible()) {
    await drawer.click();
    return { entry: (name: string) => page.getByRole('dialog', { name: 'Menu' }).getByRole('link', { name, exact: true }) };
  }
  await userMenu.click();
  return { entry: (name: string) => page.getByRole('menuitem', { name, exact: true }) };
}

/** A name no other test or earlier run on the same data shares. */
export function unique(label: string) {
  return `${label} ${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** Uncaught exceptions in the page; every fixture fails its test on any. */
function pageErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(`${page.url()}: ${e.message}`));
  return errors;
}

type ContextOptions = Parameters<Browser['newContext']>[0];

async function session(browser: Browser, options: ContextOptions, role: Role, provide: (s: Session) => Promise<void>) {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  const errors = pageErrors(page);
  await provide({ page, api: new Api(context.request), user: await signIn(page, role) });
  await context.close();
  expect(errors, `uncaught errors in the ${role}'s page`).toEqual([]);
}

export const test = base.extend<{ admin: Session; member: Session }>({
  page: async ({ page }, provide) => {
    const errors = pageErrors(page);
    await provide(page);
    expect(errors, 'uncaught errors in the page').toEqual([]);
  },
  // Each role gets its own context, so a test can hold both at once ("the other role sees it").
  admin: async ({ browser, baseURL, viewport, isMobile, hasTouch }, provide) =>
    session(browser, { baseURL, viewport, isMobile, hasTouch }, 'admin', provide),
  member: async ({ browser, baseURL, viewport, isMobile, hasTouch }, provide) =>
    session(browser, { baseURL, viewport, isMobile, hasTouch }, 'member', provide),
});

export { expect };

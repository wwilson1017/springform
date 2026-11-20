import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

// A fork's colours and logo come from frontend/public/branding/ (docs/agents/forks.md). The files
// are served through routes here, so the spec checks the mechanism and holds in a fork whose own
// branding differs.

const FORK_THEME = `
:root {
  --color-sf-accent: #1f6f78;
  --color-sf-header: #23313a;
  --color-sf-header-ink: #ffffff;
  --color-sf-highlight: #f08a24;
  --sf-header-rule: 3px;
}
:root.dark { --color-sf-accent: #2a8f9a; --color-sf-header: #151d22; }
`;
// A 3.5:1 wordmark.
const WIDE_LOGO = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 350 100" width="350" height="100"><rect width="350" height="100" fill="#888"/></svg>`;

async function serve(page: Page, path: string, body: string | null, contentType = 'text/css') {
  await page.route(path, (route) =>
    body === null ? route.fulfill({ status: 404, body: '' }) : route.fulfill({ body, contentType }),
  );
}

const rootVar = (page: Page, name: string) =>
  page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
const header = (page: Page) => page.locator('header').first();
const themeColor = (page: Page) => page.locator('meta[name="theme-color"]').getAttribute('content');

for (const [label, body] of [
  ['an empty theme.css', ''],
  ['a missing theme.css', null],
] as const) {
  test(`${label} keeps the upstream palette and header`, async ({ admin: { page } }) => {
    await serve(page, '**/branding/theme.css', body);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();
    expect(await rootVar(page, '--color-sf-accent')).toBe('#b5542d');
    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await expect(header(page)).toHaveCSS('background-color', bodyBg);
    await expect(header(page)).toHaveCSS('border-bottom-width', '1px');
    await expect(header(page)).toHaveCSS('border-bottom-color', 'rgb(229, 231, 235)');
    expect(await themeColor(page)).toBe('#f1f1e8');
  });
}

test('a fork theme.css recolours the accent and the header in light and dark', async ({ admin: { page } }) => {
  await serve(page, '**/branding/theme.css', FORK_THEME);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Apps' })).toBeVisible();

  expect(await rootVar(page, '--color-sf-accent')).toBe('#1f6f78');
  await expect(header(page)).toHaveCSS('background-color', 'rgb(35, 49, 58)');
  await expect(header(page)).toHaveCSS('border-bottom-width', '3px');
  await expect(header(page)).toHaveCSS('border-bottom-color', 'rgb(240, 138, 36)');
  await expect(header(page).getByRole('link').first()).toHaveCSS('color', 'rgb(255, 255, 255)');

  const toggle = page.getByRole('button', { name: 'Switch to dark mode' });
  await toggle.click();
  expect(await rootVar(page, '--color-sf-accent')).toBe('#2a8f9a');
  await expect(header(page)).toHaveCSS('background-color', 'rgb(21, 29, 34)');
  expect(await themeColor(page)).toBe('#151d22');
});

test('a wide logo keeps its ratio at header height', async ({ admin: { page } }) => {
  await serve(page, '**/branding/header-*.svg', WIDE_LOGO, 'image/svg+xml');
  await page.goto('/');
  const logo = header(page).locator('img:visible').first();
  await expect(logo).toBeVisible();
  const box = (await logo.boundingBox())!;
  expect(box.height).toBeCloseTo(28, 0);
  expect(box.width).toBeGreaterThan(90);
  expect(box.width).toBeLessThanOrEqual(160);
  // Nothing in the header pushes the page sideways, at 390px included.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

import { expect, test, unique } from './fixtures';

const INITIALIZE = {
  jsonrpc: '2.0', id: 1, method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'smoke', version: '0' } },
};

test('the MCP card mints a link once, the link answers, and Revoke ends it', async ({ member }) => {
  const { page, api } = member;
  const label = unique('Claude Desktop');
  await page.goto('/settings/mcp');
  await page.getByLabel('Link name').fill(label);
  await page.getByRole('button', { name: 'Create link' }).click();

  const fresh = page.getByRole('region', { name: 'New link' });
  await expect(fresh).toContainText("Copy it now: it won't be shown again.");
  const url = (await fresh.getByTestId('mcp-new-url').textContent())!;
  const path = new URL(url).pathname;
  expect(path).toMatch(/^\/mcp\/[\w-]{43}$/);
  const token = path.split('/').pop()!;
  await expect(page.getByRole('list', { name: 'Your MCP links' })).toContainText(label);

  // Only that one answer carries the token: not the list, not the page once it is dismissed.
  const listed = await api.get<Array<{ label: string }>>('/api/core/mcp/links');
  expect(listed.map(l => l.label)).toContain(label);
  expect(JSON.stringify(listed)).not.toContain(token);
  await fresh.getByRole('button', { name: 'Done' }).click();
  await expect(fresh).toBeHidden();
  await page.reload();
  await expect(page.getByRole('list', { name: 'Your MCP links' })).toContainText(label);
  expect(await page.content()).not.toContain(token);

  const call = () => api.request.post(path, { data: INITIALIZE, headers: { Accept: 'application/json, text/event-stream' } });
  expect((await call()).status()).toBe(200);

  await page.getByRole('button', { name: `Revoke ${label}` }).click();
  await page.getByRole('dialog', { name: 'Revoke link' }).getByRole('button', { name: 'Revoke' }).click();
  await expect(page.getByRole('list', { name: 'Your MCP links' }).getByText(label)).toHaveCount(0);
  expect((await call()).status()).toBe(404);
});

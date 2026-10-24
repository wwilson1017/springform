import { expect, test, unique } from './fixtures';

test("the example app's panel on a person lists its widgets, private ones only to their owner", async ({ admin, member }) => {
  const person = await admin.api.post<{ id: number }>('/api/core/contacts/people', { name: unique('Wren Example') });
  const shared = unique('Blue widget');
  const secret = unique('Private widget');
  const widget = await admin.api.post<{ id: number }>('/api/example/widgets', { name: shared, person_id: person.id });
  await admin.api.post('/api/example/widgets', { name: secret, person_id: person.id, is_private: true });

  const { page } = admin;
  await page.goto(`/people/${person.id}`);
  const panel = page.getByRole('region', { name: 'Example' });
  await expect(panel.getByRole('link')).toHaveText([shared, secret]);
  await panel.getByRole('link', { name: shared }).click();
  await expect(page).toHaveURL(new RegExp(`/example/${widget.id}$`));
  await expect(page.getByRole('textbox', { name: 'Name' })).toHaveValue(shared);

  // Example is hidden from members (hidden_by_default), so their person page has no Example panel
  // once the app panels have loaded; the API still keeps the private widget from them.
  await member.page.goto(`/people/${person.id}`);
  await expect(member.page.getByRole('region', { name: 'CRM' })).toBeVisible();
  await expect(member.page.getByRole('region', { name: 'Example' })).toHaveCount(0);
  const seen = await member.api.get<Array<{ name: string }>>(`/api/example/widgets?person_id=${person.id}`);
  expect(seen.map(w => w.name)).toEqual([shared]);
});

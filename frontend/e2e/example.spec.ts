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

  await member.page.goto(`/people/${person.id}`);
  await expect(member.page.getByRole('region', { name: 'Example' }).getByRole('link')).toHaveText([shared]);
});

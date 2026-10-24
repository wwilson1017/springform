import { expect, test, unique } from './fixtures';

interface Person { id: number; name: string; organizations: Array<{ organization_id: number; name: string; role: string }> }

test('create an organization and a person, then link them with a role', async ({ admin }) => {
  const { page, api } = admin;
  const org = unique('Smoke Bakery');
  const person = unique('Pat Example');

  await page.goto('/organizations');
  await page.getByRole('button', { name: 'New organization' }).click();
  const orgDialog = page.getByRole('dialog', { name: 'New organization' });
  await orgDialog.getByLabel('Name *').fill(org);
  await orgDialog.getByLabel('Domain').fill('bakery.example.com');
  await orgDialog.getByRole('button', { name: 'Create organization' }).click();
  await expect(page.getByRole('heading', { name: org, level: 1 })).toBeVisible();
  const orgId = Number(new URL(page.url()).pathname.split('/').pop());

  await page.goto('/people');
  await page.getByRole('button', { name: 'New person' }).click();
  const personDialog = page.getByRole('dialog', { name: 'New person' });
  await personDialog.getByLabel('Name *').fill(person);
  await personDialog.getByLabel('Email').fill('pat@example.com');
  await personDialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name: person, level: 1 })).toBeVisible();
  const personId = Number(new URL(page.url()).pathname.split('/').pop());

  const links = page.getByRole('region', { name: 'Organizations' });
  await expect(links.getByText('Not linked to an organization yet.')).toBeVisible();
  await links.getByRole('button', { name: '+ Link an organization' }).click();
  await links.getByRole('combobox', { name: 'Organization' }).fill(org);
  await links.getByRole('option', { name: org }).click();
  await links.getByLabel('Role').fill('Buyer');
  await links.getByRole('button', { name: 'Link', exact: true }).click();
  await expect(links.getByRole('link', { name: org })).toBeVisible();
  await expect(links.getByText('Buyer')).toBeVisible();

  const saved = await api.get<Person>(`/api/core/contacts/people/${personId}`);
  expect(saved.organizations).toEqual([expect.objectContaining({ organization_id: orgId, role: 'Buyer' })]);

  await links.getByRole('link', { name: org }).click();
  await expect(page.getByRole('heading', { name: org, level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'People' }).getByRole('link', { name: person })).toBeVisible();
});

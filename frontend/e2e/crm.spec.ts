import { expect, test, unique, type Session } from './fixtures';
import { serverNow } from './totp';

interface Notification { title: string }
const titles = (rows: Notification[]) => rows.map(n => n.title);

/**
 * On the record page that is open: set a reminder due before the server's frozen "now", fire it
 * with "Run now" on the Jobs page (the scheduler's own tick is frozen too), and follow its
 * notification back to the record.
 */
async function remindAndFire({ page, api }: Session, title: string) {
  const record = new URL(page.url()).pathname;
  const due = await page.evaluate(iso => {
    const d = new Date(new Date(iso).getTime() - 5 * 60_000);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }, serverNow().toISOString());
  const reminders = page.getByRole('region', { name: 'Reminders' });
  await reminders.getByRole('button', { name: 'Add reminder' }).click();
  await reminders.getByLabel('Remind me to').fill(title);
  await reminders.getByLabel('When').fill(due);
  await reminders.getByRole('button', { name: 'Set reminder' }).click();
  await expect(reminders.getByText(title, { exact: true })).toBeVisible();

  await page.goto('/jobs');
  const job = page.getByRole('listitem').filter({ has: page.getByRole('button', { name: 'core.reminders_fire_due', exact: true }) });
  // A sibling test's run may be in flight ("already running"), so press again until ours has fired.
  await expect(async () => {
    await job.getByRole('button', { name: 'Run now' }).click();
    expect(titles(await api.get('/api/core/notifications'))).toContain(`Reminder: ${title}`);
  }).toPass({ timeout: 15_000 });
  await page.reload();
  await page.getByRole('button', { name: /^Notifications/ }).click();
  await page.getByRole('dialog', { name: 'Notifications' }).getByText(`Reminder: ${title}`).click();
  await expect(page).toHaveURL(new RegExp(`${record}$`));
}

test('a deal from a person page takes a note with an @mention, a file and a reminder that fires', async ({ admin, member }) => {
  const { page, api } = admin;
  const person = await api.post<{ id: number }>('/api/core/contacts/people', { name: unique('Dana Example'), email: 'dana@example.com' });
  const dealTitle = unique('Smoke deal');

  // The deal, from the CRM's panel on the person's page.
  await page.goto(`/people/${person.id}`);
  const panel = page.getByRole('region', { name: 'CRM' });
  await expect(panel.getByText('No deals yet.')).toBeVisible();
  await panel.getByRole('button', { name: 'New deal' }).click();
  const form = page.getByRole('dialog', { name: 'New deal' });
  await form.getByLabel('Title').fill(dealTitle);
  await form.getByLabel('Value').fill('4,800.50');
  await form.getByRole('button', { name: 'Create deal' }).click();
  await expect(form).toBeHidden();
  await panel.getByRole('link', { name: new RegExp(dealTitle) }).click();
  await expect(page.getByRole('heading', { name: dealTitle })).toBeVisible();
  const dealId = Number(new URL(page.url()).pathname.split('/').pop());
  expect(await api.get(`/api/crm/deals/${dealId}`)).toMatchObject({ title: dealTitle, value_cents: 480050, stage: 'lead' });
  expect((await api.get<Array<{ id: number }>>(`/api/crm/people/${person.id}/deals`)).map(d => d.id)).toContain(dealId);

  // A note that mentions the member, who is notified and lands on the deal.
  const timeline = page.getByRole('region', { name: 'Timeline' });
  const note = timeline.getByLabel('Add a note');
  await note.fill('Quote sent, ');
  await note.pressSequentially('@Prev');
  await page.getByRole('listbox', { name: 'Mention a teammate' }).getByRole('option', { name: member.user.name }).click();
  await note.pressSequentially('please follow up');
  await expect(note).toHaveValue(`Quote sent, @[${member.user.name}](user:${member.user.id}) please follow up`);
  await timeline.getByRole('button', { name: 'Add note' }).click();
  await expect(timeline.getByText('please follow up')).toBeVisible();
  await expect.poll(async () => titles(await member.api.get('/api/core/notifications')))
    .toContainEqual(expect.stringContaining(`${admin.user.name} mentioned you`));
  await member.page.goto('/');
  await member.page.getByRole('button', { name: /^Notifications/ }).click();
  await member.page.getByRole('dialog', { name: 'Notifications' }).getByText(new RegExp(`mentioned you .*${dealTitle}`)).click();
  await expect(member.page).toHaveURL(new RegExp(`/crm/deals/${dealId}$`));
  await expect(member.page.getByRole('region', { name: 'Timeline' }).getByText('please follow up')).toBeVisible();

  // A file on the deal.
  const files = page.getByRole('region', { name: 'Attachments' });
  const quote = Buffer.from('Forty boxes, delivered by noon.\n');
  await files.locator('input[type=file]').setInputFiles({ name: 'quote.txt', mimeType: 'text/plain', buffer: quote });
  await expect(files.getByRole('link', { name: 'Download quote.txt' })).toBeVisible();
  expect(await api.get(`/api/core/files?entity_type=crm.deal&entity_id=${dealId}`))
    .toEqual([expect.objectContaining({ filename: 'quote.txt', byte_size: quote.length })]);

  // A reminder on the person (the deal page's own is the next test).
  await page.goto(`/people/${person.id}`);
  await remindAndFire(admin, unique('Call Dana back'));
});

test('F2: a reminder set on the deal page fires', async ({ admin }) => {
  const deal = await admin.api.post<{ id: number }>('/api/crm/deals', { title: unique('Reminder deal'), stage: 'lead', value_cents: 0 });
  await admin.page.goto(`/crm/deals/${deal.id}`);
  await remindAndFire(admin, unique('Chase the deposit'));
});

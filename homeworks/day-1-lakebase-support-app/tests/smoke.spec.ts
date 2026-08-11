import { expect, test } from '@playwright/test';

const tickets = [
  {
    ticket_id: 1,
    title: 'Cannot access the analytics workspace',
    status: 'open',
    priority: 'high',
    created_by: 'Marina Costa',
    created_at: '2026-08-05T10:00:00.000Z',
    updated_at: '2026-08-05T10:00:00.000Z',
    message_count: 2,
    last_message_at: '2026-08-05T10:05:00.000Z',
  },
  {
    ticket_id: 2,
    title: 'Question about cluster runtime version',
    status: 'in_progress',
    priority: 'medium',
    created_by: 'Rafael Lima',
    created_at: '2026-08-05T09:00:00.000Z',
    updated_at: '2026-08-05T09:00:00.000Z',
    message_count: 2,
    last_message_at: '2026-08-05T09:05:00.000Z',
  },
];

test.beforeEach(async ({ page }) => {
  await page.route('**/api/stats', async (route) => {
    await route.fulfill({ json: { total: 3, by_status: { open: 1, in_progress: 1, resolved: 1 } } });
  });

  await page.route('**/api/tickets**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === 'GET' && url.pathname === '/api/tickets') {
      await route.fulfill({ json: tickets });
      return;
    }

    if (request.method() === 'GET' && url.pathname === '/api/tickets/1') {
      await route.fulfill({
        json: {
          ticket: tickets[0],
          messages: [
            { message_id: 1, ticket_id: 1, message_text: 'I receive a permission error.', author: 'Marina Costa', created_at: '2026-08-05T10:00:00.000Z' },
            { message_id: 2, ticket_id: 1, message_text: 'The platform team is reviewing access.', author: 'Support team', created_at: '2026-08-05T10:05:00.000Z' },
          ],
        },
      });
      return;
    }

    if (request.method() === 'POST' && url.pathname === '/api/tickets') {
      await route.fulfill({
        status: 201,
        json: { ...tickets[0], ticket_id: 99, title: 'New access request', created_by: 'Gabriel' },
      });
      return;
    }

    await route.fulfill({ status: 404, json: { error: 'Not found' } });
  });
});

test('loads support tickets and their Lakebase-backed detail', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Support operations console' })).toBeVisible();
  await expect(page.getByText('All tickets')).toBeVisible();
  await expect(page.getByText('Cannot access the analytics workspace')).toBeVisible();

  await page.getByText('Cannot access the analytics workspace').click();
  await expect(page.getByRole('heading', { name: 'Cannot access the analytics workspace' })).toBeVisible();
  await expect(page.getByText('The platform team is reviewing access.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Update status' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add message' })).toBeVisible();
});

test('shows the new-ticket form with required operational fields', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: 'New ticket' }).click();
  await expect(page.getByRole('heading', { name: 'Create a support ticket' })).toBeVisible();
  await expect(page.getByLabel('Title')).toBeVisible();
  await expect(page.getByLabel('Created by')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create ticket' })).toBeVisible();
});

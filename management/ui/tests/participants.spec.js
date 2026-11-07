/*
 * Copyright (c) 2026 IndustryFusion Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { expect, test } from '@playwright/test';

import { enterAdminMode, open, register, reset, rowOf, STAND_INS } from './helpers.js';

const ID = STAND_INS ? 'urn:ui:new' : 'urn:ui-browser:owner';

test.beforeEach(async ({ request }) => reset(request));

test('reads work without signing in', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Needs a participant to look at');
  await request.post('/test/pair');
  await open(page, 'Participants');
  const row = rowOf(page, 'urn:ui:fo');
  await expect(row).toContainText('factory_owner');
  await expect(row).toContainText('Yes');
});

test('register a hosted participant, see its credentials, set reachability, and delete it', async ({ page }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  await register(page, ID);
  const credentials = page.getByRole('region', { name: 'Credentials' });
  await expect(credentials).toContainText(ID);
  const secret = await credentials.locator('code').textContent();
  expect(secret.length).toBeGreaterThan(5);
  await credentials.getByRole('button', { name: 'Close' }).click();
  await expect(credentials).toHaveCount(0);

  await rowOf(page, ID).getByRole('button', { name: 'Show credentials' }).click();
  await expect(credentials.locator('code')).toHaveText(secret);
  await credentials.getByRole('button', { name: 'Close' }).click();

  const row = rowOf(page, ID);
  await row.getByRole('button', { name: 'Make reachable' }).click();
  await expect(row.getByRole('button', { name: 'Make unreachable' })).toBeVisible({ timeout: 60000 });
  await expect(row.getByRole('cell').nth(3)).toHaveText('Yes');
  await row.getByRole('button', { name: 'Make unreachable' }).click();
  await expect(row.getByRole('button', { name: 'Make reachable' })).toBeVisible({ timeout: 60000 });

  page.on('dialog', (dialog) => dialog.accept());
  await row.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByRole('cell', { name: ID, exact: true })).toHaveCount(0, { timeout: 180000 });
});

test('cancelling a delete keeps the participant', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Needs a participant to look at');
  await request.post('/test/pair');
  await open(page, 'Participants');
  await enterAdminMode(page);
  page.on('dialog', (dialog) => dialog.dismiss());
  await rowOf(page, 'urn:ui:fo').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByRole('cell', { name: 'urn:ui:fo', exact: true })).toBeVisible();
});

test('register an external participant', async ({ page }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  const form = page.getByRole('form', { name: 'Register a participant' });
  await form.getByLabel('Participant id').fill('urn:ui:external');
  await form.getByLabel('Hosted here').uncheck();
  await form.getByLabel('Adapter URL').fill('http://adapter.example');
  await form.getByLabel('DSP URL').fill('http://dsp.example');
  await form.getByRole('button', { name: 'Register' }).click();
  const row = rowOf(page, 'urn:ui:external');
  await expect(row.getByRole('cell').nth(2)).toHaveText('No', { timeout: 60000 });
  await expect(page.getByRole('region', { name: 'Credentials' })).toContainText('urn:ui:external');
  if (!STAND_INS) {
    page.on('dialog', (dialog) => dialog.accept());
    await row.getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByRole('cell', { name: 'urn:ui:external', exact: true })).toHaveCount(0, { timeout: 60000 });
  }
});

test('create demo participants', async ({ page }) => {
  test.skip(!STAND_INS, 'A deployment has its own demo participants');
  await open(page, 'Participants');
  await enterAdminMode(page);
  await page.getByRole('button', { name: 'Create demo participants' }).click();
  await expect(page.getByRole('cell', { name: 'urn:demo:fo', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'urn:demo:mb', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Credentials' }).locator('dl')).toHaveCount(2);
});

test("an API error on registering is shown, with the API's message", async ({ page, request }) => {
  test.skip(!STAND_INS, 'Needs the stand-ins to fail');
  await request.post('/test/foreign-client');
  await open(page, 'Participants');
  await enterAdminMode(page);
  const form = page.getByRole('form', { name: 'Register a participant' });
  await form.getByLabel('Participant id').fill('urn:ui:taken');
  await form.getByRole('button', { name: 'Register' }).click();
  await expect(page.getByRole('alert')).toContainText("isn't a participant's");
  await expect(form.getByLabel('Participant id')).toHaveValue('urn:ui:taken');
});

test('a validation error from the API is shown', async ({ page }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  const form = page.getByRole('form', { name: 'Register a participant' });
  await form.getByLabel('Participant id').fill('has a space');
  await form.getByRole('button', { name: 'Register' }).click();
  await expect(page.getByRole('alert')).toContainText('participant_id');
});

test('an error reading the list is shown', async ({ page }) => {
  await page.route('**/api/participants', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"The registry is unavailable"}' }),
  );
  await open(page, 'Participants');
  await expect(page.getByRole('alert')).toHaveText('The registry is unavailable');
});

test('a non-JSON error from something in between is shown by its status', async ({ page }) => {
  await page.route('**/api/participants', (route) =>
    route.fulfill({ status: 502, contentType: 'text/html', body: '<html>Bad gateway</html>' }),
  );
  await open(page, 'Participants');
  await expect(page.getByRole('alert')).toHaveText('The server answered 502');
});

test('an API that cannot be reached is shown', async ({ page }) => {
  await page.route('**/api/participants', (route) => route.abort());
  await open(page, 'Participants');
  await expect(page.getByRole('alert')).toHaveText('The management API could not be reached');
});

test('works without company details', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Depends on the data');
  await request.post('/test/pair');
  await open(page, 'Participants');
  await expect(page.getByRole('cell', { name: 'urn:ui:fo', exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Company' })).toHaveCount(0);
});

test('shows company details when available', async ({ page }) => {
  await page.route('**/api/participants', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          participant_id: 'urn:ifric:company',
          participant_type: 'x#factory_owner',
          hosted: true,
          externally_reachable: false,
          company_name: 'Acme Machines',
          company_category: 'manufacturer',
          city: 'Bengaluru',
          country: 'India',
        },
        { participant_id: 'urn:other', participant_type: 'x#machine_builder', hosted: true },
      ]),
    }),
  );
  await open(page, 'Participants');
  const row = rowOf(page, 'urn:ifric:company');
  for (const text of ['Acme Machines', 'manufacturer', 'Bengaluru', 'India']) await expect(row).toContainText(text);
  await expect(rowOf(page, 'urn:other')).toBeVisible();
});

test('leaving admin mode takes shown secrets away', async ({ page, request }) => {
  await request.post('/test/pair');
  await open(page, 'Participants');
  await enterAdminMode(page);
  await rowOf(page, 'urn:ui:fo').getByRole('button', { name: 'Show credentials' }).click();
  await expect(page.getByRole('region', { name: 'Credentials' })).toBeVisible();
  await page.getByRole('button', { name: 'Leave admin mode' }).click();
  await expect(page.getByRole('region', { name: 'Credentials' })).toHaveCount(0);
});

test('a company field of an unexpected type does not blank the page', async ({ page, request }) => {
  await request.post('/test/pair');
  await page.route('**/api/participants', async (route) => {
    const answer = await route.fetch();
    const list = await answer.json();
    list[0].company_name = { html: 'x' };
    await route.fulfill({ response: answer, json: list });
  });
  await open(page, 'Participants');
  await expect(page.getByRole('cell', { name: 'urn:ui:fo', exact: true })).toBeVisible();
});

test('an action error stays visible when the reload after it fails too', async ({ page, request }) => {
  await request.post('/test/pair');
  await open(page, 'Participants');
  await enterAdminMode(page);
  await page.route('**/api/participants/**', (route) =>
    route.fulfill({ status: 409, json: { detail: 'The action failed like this' } }),
  );
  await page.route('**/api/participants', (route) =>
    route.request().method() === 'GET' ? route.fulfill({ status: 503, json: { detail: 'The list failed' } }) : route.continue(),
  );
  page.on('dialog', (dialog) => dialog.accept());
  await rowOf(page, 'urn:ui:fo').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByRole('alert')).toContainText('The action failed like this');
});

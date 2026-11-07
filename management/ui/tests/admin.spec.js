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

import { ADMIN_SECRET, enterAdminMode, open, reset, STAND_INS } from './helpers.js';

test.beforeEach(async ({ request }) => reset(request));

test('admin actions are unavailable without admin mode', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Needs a participant to look at');
  await request.post('/test/pair');
  await open(page, 'Participants');
  await expect(page.getByRole('cell', { name: 'urn:ui:fo', exact: true })).toBeVisible();
  for (const name of ['Register', 'Create demo participants', 'Show credentials', 'Make reachable', 'Delete']) {
    await expect(page.getByRole('button', { name })).toHaveCount(0);
  }
  await page.getByRole('tab', { name: 'Policies' }).click();
  for (const name of ['Show', 'Approve', 'Deny', 'Reset']) {
    await expect(page.getByRole('button', { name })).toHaveCount(0);
  }
});

test('a wrong secret is refused with the API error, and stays out of admin mode', async ({ page }) => {
  await open(page, 'Health');
  await page.getByRole('button', { name: 'Admin mode' }).click();
  await page.getByLabel('Client secret').fill('wrong');
  await page.getByRole('button', { name: 'Enter' }).click();
  await expect(page.getByRole('alert')).toHaveText('Wrong client credentials');
  await expect(page.getByRole('button', { name: 'Leave admin mode' })).toHaveCount(0);
});

test('the secret is not kept in the browser, and a reload leaves admin mode', async ({ page, context }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(stored).toBe('{}');
  expect(await page.evaluate(() => document.cookie)).toBe('');
  expect(await context.cookies()).toEqual([]);
  expect(await page.content()).not.toContain(ADMIN_SECRET);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Admin mode' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Leave admin mode' })).toHaveCount(0);
});

test('leaving admin mode takes the actions away', async ({ page }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  await expect(page.getByRole('button', { name: 'Create demo participants' })).toBeVisible();
  await page.getByRole('button', { name: 'Leave admin mode' }).click();
  await expect(page.getByRole('button', { name: 'Create demo participants' })).toHaveCount(0);
});

test('a token is refreshed through the token route when it runs out', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Depends on a short-lived token');
  await page.clock.install();
  await request.post('/test/short-tokens');
  await open(page, 'Participants');
  const sent = [];
  page.on('request', (call) => {
    if (call.url().endsWith('/api/admin/token')) sent.push(call.postDataJSON());
  });
  await enterAdminMode(page);
  expect(sent).toHaveLength(1);
  // The token lives 40 seconds, and is refreshed 30 seconds before that: at 10 seconds.
  await page.clock.runFor(11000);
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[1].client_secret).toBe(ADMIN_SECRET);
  await expect(page.getByRole('button', { name: 'Leave admin mode' })).toBeVisible();
});

test('a call refused with 401 fetches a new token and is tried again', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Depends on the stand-ins');
  await request.post('/test/pair');
  await open(page, 'Participants');
  await enterAdminMode(page);
  let refused = false;
  await page.route('**/credentials', async (route) => {
    if (!refused) {
      refused = true;
      await route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Invalid token"}' });
    } else {
      await route.continue();
    }
  });
  const tokenCall = page.waitForRequest('**/api/admin/token');
  await page.getByRole('row').filter({ hasText: 'urn:ui:fo' }).getByRole('button', { name: 'Show credentials' }).click();
  await tokenCall;
  await expect(page.getByRole('region', { name: 'Credentials' })).toContainText('urn:ui:fo');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('a failed refresh tells the administrator why admin mode ended', async ({ page, request }) => {
  await request.post('/test/short-tokens');
  await open(page, 'Participants');
  await enterAdminMode(page);
  await page.route('**/api/admin/token', (route) =>
    route.fulfill({ status: 503, json: { detail: 'Keycloak is unavailable' } }),
  );
  await expect(page.getByRole('button', { name: 'Leave admin mode' })).toHaveCount(0, { timeout: 20000 });
  await expect(page.getByRole('alert')).toContainText('Keycloak is unavailable');
});
